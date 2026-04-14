const interviewToken = window.INTERVIEW_TOKEN;
const waitingUrl = window.WAITING_URL;
const enterUrl = window.ENTER_URL;
const interviewTime = new Date(window.INTERVIEW_TIME);
const countdownText = document.getElementById('countdownText');
const compatPercent = document.getElementById('compatPercent');
const compatProgress = document.getElementById('compatProgress');
const systemStatus = document.getElementById('systemStatus');
const micStatus = document.getElementById('micStatus');
const speakerStatus = document.getElementById('speakerStatus');
const cameraStatus = document.getElementById('cameraStatus');
const internetStatus = document.getElementById('internetStatus');
const micMeter = document.getElementById('micMeter');
const cameraPreview = document.getElementById('cameraPreview');
const speakerConfirmWrap = document.getElementById('speakerConfirmWrap');
const micTestBtn = document.getElementById('micTestBtn');
const speakerTestBtn = document.getElementById('speakerTestBtn');
const speakerYesBtn = document.getElementById('speakerYesBtn');

let micStream = null;
let cameraStream = null;
let audioContext = null;
let analyser = null;
let frequencyData = null;
let meterFrame = null;
let tick = null;
let speakerPending = false;
let saveQueue = Promise.resolve();
const persistedStatuses = {};

const checks = {
    system: 'pending',
    mic: 'pending',
    speaker: 'pending',
    camera: 'pending',
    internet: 'pending',
};

function setStatus(element, status, label) {
    if (!element) return;
    const lower = (status || '').toLowerCase();
    element.className = lower === 'passed' || lower === 'ready' ? 'compat-pass' : lower === 'failed' ? 'compat-fail' : 'compat-warn';
    element.textContent = label;
}

function updateProgress() {
    const total = Object.keys(checks).length;
    const passed = Object.values(checks).filter((item) => item === 'passed').length;
    const percent = Math.round((passed / total) * 100);
    if (compatPercent) compatPercent.textContent = `${percent}%`;
    if (compatProgress) compatProgress.style.width = `${percent}%`;
}

function setCheck(key, status, label) {
    checks[key] = status;
    updateProgress();
    switch (key) {
        case 'system':
            setStatus(systemStatus, status, label);
            break;
        case 'mic':
            setStatus(micStatus, status, label);
            break;
        case 'speaker':
            setStatus(speakerStatus, status, label);
            break;
        case 'camera':
            setStatus(cameraStatus, status, label);
            break;
        case 'internet':
            setStatus(internetStatus, status, label);
            break;
    }

    if (status === 'passed' || status === 'failed') {
        queueCompatibilitySave(key, status, label);
    }
}

function getCheckDetails(key, status) {
    const readable = {
        system: 'Browser and device readiness',
        mic: 'Microphone test completed',
        speaker: 'Speaker playback confirmed',
        camera: 'Camera preview confirmed',
        internet: 'Network connectivity checked',
    };
    return `${readable[key] || key} - ${status}`;
}

function queueCompatibilitySave(checkName, status, label) {
    if (!interviewToken) return;
    const fingerprint = `${checkName}:${status}`;
    if (persistedStatuses[checkName] === fingerprint) return;
    persistedStatuses[checkName] = fingerprint;
    const details = getCheckDetails(checkName, status) + (label ? ` (${label})` : '');
    saveQueue = saveQueue
        .then(() => fetch(`/api/interviews/${encodeURIComponent(interviewToken)}/compatibility`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                check_name: checkName,
                status,
                details,
            }),
        }))
        .catch(() => {});
}

function refreshCountdown() {
    const diff = interviewTime.getTime() - Date.now();
    const remaining = Math.max(0, Math.ceil(diff / 1000));
    if (countdownText) {
        countdownText.textContent = remaining > 0 ? `${remaining}s` : 'Ready now';
    }
}

function initMicMeter() {
    if (!micMeter) return;
    micMeter.innerHTML = '';
    for (let i = 0; i < 8; i += 1) {
        const bar = document.createElement('span');
        micMeter.appendChild(bar);
    }
}

function animateMeter() {
    if (!analyser || !frequencyData || !micMeter) return;
    analyser.getByteFrequencyData(frequencyData);
    const bars = micMeter.querySelectorAll('span');
    const step = Math.max(1, Math.floor(frequencyData.length / bars.length));
    bars.forEach((bar, index) => {
        const value = frequencyData[index * step] || 0;
        bar.style.height = `${8 + Math.round((value / 255) * 22)}px`;
    });
    meterFrame = requestAnimationFrame(animateMeter);
}

function stopMicMeter() {
    if (meterFrame) cancelAnimationFrame(meterFrame);
    meterFrame = null;
    if (audioContext) audioContext.close().catch(() => {});
    audioContext = null;
    analyser = null;
    frequencyData = null;
}

async function testInternet() {
    try {
        await fetch(`/api/ping?ts=${Date.now()}`, { cache: 'no-store' });
        setCheck('internet', 'passed', 'Passed');
    } catch (error) {
        setCheck('internet', 'failed', 'Failed');
    }
}

async function testMicrophone() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        if (micStream) micStream.getTracks().forEach((track) => track.stop());
        micStream = stream;
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 64;
        frequencyData = new Uint8Array(analyser.frequencyBinCount);
        source.connect(analyser);
        animateMeter();
        setCheck('mic', 'passed', 'Microphone Passed');
        setCheck('system', 'passed', 'Ready');
    } catch (error) {
        setCheck('mic', 'failed', 'Failed');
    }
}

function testSpeaker() {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
        setCheck('speaker', 'failed', 'Failed');
        return;
    }
    speakerPending = true;
    if (speakerConfirmWrap) speakerConfirmWrap.hidden = false;
    setCheck('speaker', 'ready', 'Pending');
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance('Speaker test. Please confirm that you can hear this sound.');
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
}

async function testCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
        cameraStream = stream;
        if (cameraPreview) cameraPreview.srcObject = stream;
        setCheck('camera', 'passed', 'Passed');
    } catch (error) {
        setCheck('camera', 'failed', 'Failed');
    }
}

function runBrowserCheck() {
    const online = navigator.onLine;
    const hasMedia = Boolean(navigator.mediaDevices?.getUserMedia);
    if (online && hasMedia) {
        setCheck('system', 'passed', 'Ready');
    } else {
        setCheck('system', 'ready', 'Pending');
    }
}

if (micTestBtn) micTestBtn.addEventListener('click', testMicrophone);
if (speakerTestBtn) speakerTestBtn.addEventListener('click', testSpeaker);
if (speakerYesBtn) {
    speakerYesBtn.addEventListener('click', () => {
        speakerPending = false;
        if (speakerConfirmWrap) speakerConfirmWrap.hidden = true;
        setCheck('speaker', 'passed', 'Passed');
    });
}

setCheck('system', 'ready', 'Ready');
setCheck('mic', 'ready', 'Pending');
setCheck('speaker', 'ready', 'Pending');
setCheck('camera', 'ready', 'Pending');
setCheck('internet', navigator.onLine ? 'passed' : 'failed', navigator.onLine ? 'Passed' : 'Failed');

runBrowserCheck();
initMicMeter();
testInternet();
testCamera();
refreshCountdown();
tick = setInterval(refreshCountdown, 1000);

window.addEventListener('beforeunload', () => {
    stopMicMeter();
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
});
