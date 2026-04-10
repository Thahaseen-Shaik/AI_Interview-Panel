const webcam = document.getElementById('webcam');
const screenPreview = document.getElementById('screenPreview');
const chatMessages = document.getElementById('chatMessages');
const interviewShell = document.getElementById('interviewShell');
const compatibilityOverlay = document.getElementById('compatibilityOverlay');
const warningBanner = document.getElementById('warningBanner');

const startBtn = document.getElementById('startBtn');
const shareBtn = document.getElementById('shareBtn');
const listenBtn = document.getElementById('listenBtn');
const endBtn = document.getElementById('endBtn');
const runCompatBtn = document.getElementById('runCompatBtn');
const shareCompatBtn = document.getElementById('shareCompatBtn');
const continueCompatBtn = document.getElementById('continueCompatBtn');

const interviewToken = window.INTERVIEW_TOKEN;
const camStatus = document.getElementById('camStatus');
const screenStatus = document.getElementById('screenStatus');
const checkSystem = document.getElementById('checkSystem');
const checkMic = document.getElementById('checkMic');
const checkCamera = document.getElementById('checkCamera');
const checkScreen = document.getElementById('checkScreen');
const checkInternet = document.getElementById('checkInternet');
const checkBrowser = document.getElementById('checkBrowser');
const checkFullscreen = document.getElementById('checkFullscreen');
const compatPercent = document.getElementById('compatPercent');
const compatProgress = document.getElementById('compatProgress');
const micMeter = document.getElementById('micMeter');

let recognition;
let ollamaContext = [];
let startTime = null;
let finalized = false;
let interviewStarted = false;
let interviewEntered = false;
let cameraStream = null;
let screenStream = null;
let audioContext = null;
let analyser = null;
let micData = null;
let meterFrame = null;
let warningTimer = {};
let screenSharePrompted = false;

const transcript = [];

const PRECHECK_KEYS = ['system', 'mic', 'camera', 'screen', 'internet', 'browser'];
const CHECK_KEYS = [...PRECHECK_KEYS, 'fullscreen'];
const checkState = {
    system: 'pending',
    mic: 'pending',
    camera: 'pending',
    screen: 'pending',
    internet: 'pending',
    browser: 'pending',
    fullscreen: 'pending',
};

function addTranscriptMessage(speaker, content) {
    transcript.push({
        speaker,
        content,
        created_at: new Date().toISOString(),
    });
}

function addMessage(text, sender, track = true) {
    const div = document.createElement('div');
    div.className = `message msg-${sender}`;
    div.innerText = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    if (track) {
        addTranscriptMessage(sender === 'ai' ? 'ai' : 'candidate', text);
    }
}

function showWarning(message) {
    if (!warningBanner) {
        return;
    }
    warningBanner.hidden = false;
    warningBanner.textContent = message;
}

function hideWarning() {
    if (!warningBanner) {
        return;
    }
    warningBanner.hidden = true;
    warningBanner.textContent = '';
}

function stateClassFor(status) {
    const lower = (status || '').toLowerCase();
    if (['passed', 'ready', 'supported', 'active', 'allowed'].includes(lower)) {
        return 'compat-pass';
    }
    if (['failed', 'unsupported', 'blocked', 'denied'].includes(lower)) {
        return 'compat-fail';
    }
    return 'compat-warn';
}

function displayStatus(element, status, text) {
    element.className = stateClassFor(status);
    element.textContent = text;
}

function updateProgress() {
    const passed = CHECK_KEYS.filter((key) => {
        const status = (checkState[key] || '').toLowerCase();
        return ['passed', 'ready', 'supported', 'active', 'allowed'].includes(status);
    }).length;
    const percent = Math.round((passed / CHECK_KEYS.length) * 100);
    compatPercent.textContent = `${percent}%`;
    compatProgress.style.width = `${percent}%`;
    continueCompatBtn.disabled = !PRECHECK_KEYS.every((key) => {
        const status = (checkState[key] || '').toLowerCase();
        return ['passed', 'ready', 'supported', 'active', 'allowed'].includes(status);
    });
    return percent;
}

async function logCompatibility(check_name, status, details = '') {
    try {
        await fetch(`/api/interviews/${interviewToken}/compatibility`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ check_name, status, details }),
        });
    } catch (error) {
        console.warn('Compatibility log failed:', error);
    }
}

async function logEvent(event_type, details = '') {
    const now = Date.now();
    if (warningTimer[event_type] && now - warningTimer[event_type] < 2000) {
        return;
    }
    warningTimer[event_type] = now;

    try {
        await fetch(`/api/interviews/${interviewToken}/event`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_type, details }),
        });
    } catch (error) {
        console.warn('Security event log failed:', error);
    }
}

function setCheck(key, element, status, text, details = '') {
    checkState[key] = status;
    displayStatus(element, status, text);
    updateProgress();
    logCompatibility(key, status, details);
}

function initMicMeter() {
    const bars = Array.from({ length: 8 }, () => document.createElement('span'));
    micMeter.innerHTML = '';
    bars.forEach((bar) => micMeter.appendChild(bar));
}

function animateMicMeter() {
    if (!analyser || !micData) {
        return;
    }
    analyser.getByteFrequencyData(micData);
    const bars = micMeter.querySelectorAll('span');
    const step = Math.max(1, Math.floor(micData.length / bars.length));
    bars.forEach((bar, index) => {
        const value = micData[index * step] || 0;
        const height = 6 + Math.round((value / 255) * 22);
        bar.style.height = `${height}px`;
    });
    meterFrame = requestAnimationFrame(animateMicMeter);
}

function startMicVisualization(stream) {
    try {
        stopMicVisualization();
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 64;
        micData = new Uint8Array(analyser.frequencyBinCount);
        source.connect(analyser);
        micMeter.classList.add('active');
        animateMicMeter();
    } catch (error) {
        console.warn('Mic visualizer unavailable:', error);
    }
}

function stopMicVisualization() {
    if (meterFrame) {
        cancelAnimationFrame(meterFrame);
        meterFrame = null;
    }
    if (audioContext) {
        audioContext.close().catch(() => {});
    }
    audioContext = null;
    analyser = null;
    micData = null;
    micMeter.classList.remove('active');
    micMeter.querySelectorAll('span').forEach((bar) => {
        bar.style.height = '8px';
    });
}

function updateControlState() {
    const complete = PRECHECK_KEYS.every((key) => {
        const status = (checkState[key] || '').toLowerCase();
        return ['passed', 'ready', 'supported', 'active', 'allowed'].includes(status);
    });

    continueCompatBtn.disabled = !complete;

    const readyToStart = Boolean(interviewEntered && complete && screenStream && cameraStream && document.fullscreenElement);
    startBtn.disabled = !readyToStart;
    startBtn.style.opacity = readyToStart ? '1' : '0.55';
    startBtn.innerText = readyToStart ? 'START INTERVIEW' : 'START INTERVIEW';
}

async function markStarted() {
    try {
        await fetch(`/api/interviews/${interviewToken}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
    } catch (error) {
        console.warn('Unable to mark interview as started:', error);
    }
}

async function startCameraAndMicCheck() {
    if (!navigator.mediaDevices?.getUserMedia) {
        setCheck('camera', checkCamera, 'failed', 'Failed', 'getUserMedia unsupported');
        setCheck('mic', checkMic, 'failed', 'Failed', 'getUserMedia unsupported');
        setCheck('system', checkSystem, 'failed', 'Not Ready', 'Media capture unsupported');
        return false;
    }

    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true,
        });
        webcam.srcObject = cameraStream;
        camStatus.className = 'status-badge status-on';
        camStatus.innerText = 'CAM ON';

        setCheck('camera', checkCamera, 'passed', 'Passed', 'Webcam preview active');
        setCheck('mic', checkMic, 'passed', 'Passed', 'Microphone permission granted');
        setCheck('system', checkSystem, 'passed', 'Ready', 'Device access granted');
        startMicVisualization(cameraStream);
        return true;
    } catch (error) {
        console.error('Camera/mic access denied:', error);
        camStatus.className = 'status-badge status-off';
        camStatus.innerText = 'CAM OFF';
        setCheck('camera', checkCamera, 'failed', 'Failed', error.message || 'Camera permission denied');
        setCheck('mic', checkMic, 'failed', 'Failed', error.message || 'Microphone permission denied');
        setCheck('system', checkSystem, 'failed', 'Not Ready', 'Permissions denied');
        return false;
    }
}

async function runInternetCheck() {
    const startedAt = performance.now();
    try {
        await fetch(`/api/ping?ts=${Date.now()}`, { cache: 'no-store' });
        const latency = Math.round(performance.now() - startedAt);
        const status = latency <= 600 ? 'passed' : 'ready';
        const label = latency <= 600 ? 'Passed' : 'Warning';
        setCheck('internet', checkInternet, status, label, `Latency ${latency}ms`);
    } catch (error) {
        setCheck('internet', checkInternet, 'failed', 'Failed', 'No internet or server unreachable');
    }
}

function runBrowserCheck() {
    const required = [
        Boolean(navigator.mediaDevices?.getUserMedia),
        Boolean(navigator.mediaDevices?.getDisplayMedia),
        Boolean(document.documentElement?.requestFullscreen),
        Boolean(window.getComputedStyle),
        Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
    ];

    const supported = required.every(Boolean);
    const browserName = navigator.userAgent.includes('Edg/')
        ? 'Edge'
        : navigator.userAgent.includes('Chrome/')
            ? 'Chrome'
            : navigator.userAgent.includes('Firefox/')
                ? 'Firefox'
                : navigator.userAgent.includes('Safari/')
                    ? 'Safari'
                    : 'Unknown';

    if (supported && (browserName === 'Chrome' || browserName === 'Edge')) {
        setCheck('browser', checkBrowser, 'passed', 'Passed', `${browserName} supported`);
    } else if (supported) {
        setCheck('browser', checkBrowser, 'ready', 'Warning', `${browserName} may have limited support`);
    } else {
        setCheck('browser', checkBrowser, 'failed', 'Failed', 'Missing required browser APIs');
    }
}

async function runCompatibilityChecks() {
    runBrowserCheck();
    await runInternetCheck();
    await startCameraAndMicCheck();

    if (!screenSharePrompted) {
        setCheck('screen', checkScreen, 'ready', 'Pending', 'Click Share Screen to complete');
    }

    setCheck('fullscreen', checkFullscreen, 'ready', 'Ready', 'Will be enforced when proceeding');
    updateControlState();
}

async function startScreenShare() {
    if (!navigator.mediaDevices?.getDisplayMedia) {
        setCheck('screen', checkScreen, 'failed', 'Failed', 'Screen share unsupported');
        return;
    }

    screenSharePrompted = true;

    try {
        const stream = await navigator.mediaDevices.getDisplayMedia({
            video: {
                frameRate: 15,
                displaySurface: 'monitor',
            },
            audio: false,
        });

        const [track] = stream.getVideoTracks();
        const settings = track?.getSettings?.() || {};

        if (settings.displaySurface && settings.displaySurface !== 'monitor') {
            track.stop();
            setCheck('screen', checkScreen, 'failed', 'Failed', 'Choose Entire Screen');
            showWarning('Please share your entire screen, not just a window or tab.');
            return;
        }

        if (screenStream) {
            screenStream.getTracks().forEach((t) => t.stop());
        }

        screenStream = stream;
        screenPreview.srcObject = stream;
        screenPreview.hidden = false;
        screenStatus.className = 'status-badge status-on';
        screenStatus.innerText = 'SCREEN ON';
        setCheck('screen', checkScreen, 'passed', 'Passed', 'Entire screen shared');

        track.onended = () => {
            screenStream = null;
            screenPreview.srcObject = null;
            screenPreview.hidden = true;
            screenStatus.className = 'status-badge status-off';
            screenStatus.innerText = 'SCREEN OFF';
            setCheck('screen', checkScreen, 'ready', 'Pending', 'Screen share ended');
            updateControlState();
            if (interviewStarted && !finalized) {
                showWarning('Screen sharing was stopped. Please share again to continue.');
                logEvent('screen_share_stopped', 'Candidate stopped screen sharing');
            }
        };

        hideWarning();
        updateControlState();
    } catch (error) {
        console.error('Screen share failed:', error);
        setCheck('screen', checkScreen, 'failed', 'Failed', 'Screen share permission denied');
    }
}

async function enterInterviewPanel() {
    const complete = PRECHECK_KEYS.every((key) => ['passed', 'ready', 'supported', 'active', 'allowed'].includes((checkState[key] || '').toLowerCase()));
    if (!complete || !screenStream || !cameraStream) {
        showWarning('Please complete every check before proceeding to the interview.');
        return;
    }

    compatibilityOverlay.hidden = true;
    interviewShell.hidden = false;

    try {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        if (!document.fullscreenElement && interviewShell.requestFullscreen) {
            await interviewShell.requestFullscreen();
        } else if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
            await document.documentElement.requestFullscreen();
        }
        setCheck('fullscreen', checkFullscreen, 'passed', 'Active', 'Fullscreen enforced');
    } catch (error) {
        console.warn('Fullscreen request failed:', error);
        setCheck('fullscreen', checkFullscreen, 'failed', 'Failed', 'Fullscreen permission denied');
        showWarning('Fullscreen mode is required to start the interview.');
        logEvent('fullscreen_request_failed', error.message || 'Fullscreen request denied');
        interviewShell.hidden = true;
        compatibilityOverlay.hidden = false;
        return;
    }

    interviewEntered = true;
    updateControlState();
    hideWarning();
    logEvent('compatibility_complete', 'Candidate passed compatibility checks and entered interview panel');
}

function allChecksPass() {
    return PRECHECK_KEYS.every((key) => ['passed', 'ready', 'supported', 'active', 'allowed'].includes((checkState[key] || '').toLowerCase()));
}

function enforceFullscreenState() {
    if (!interviewEntered || finalized) {
        return;
    }

    const inFullscreen = Boolean(document.fullscreenElement);
    if (!inFullscreen) {
        showWarning('Fullscreen mode was exited. Please return to fullscreen to continue.');
        setCheck('fullscreen', checkFullscreen, 'failed', 'Exited', 'Fullscreen exited during interview');
        logEvent('fullscreen_exit', 'Candidate exited fullscreen mode');
    } else {
        hideWarning();
        setCheck('fullscreen', checkFullscreen, 'passed', 'Active', 'Fullscreen active');
    }
    updateControlState();
}

async function finalizeInterview(reason) {
    if (finalized) {
        return;
    }
    finalized = true;

    const durationMinutes = startTime ? (Date.now() - startTime) / 60000 : 0;
    try {
        const response = await fetch(`/api/interviews/${interviewToken}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                duration_minutes: durationMinutes,
                transcript,
                reason,
            }),
        });
        const data = await response.json();

        const resultBox = document.createElement('div');
        resultBox.style.textAlign = 'center';
        resultBox.style.padding = '1rem';
        resultBox.style.color = '#4ade80';
        resultBox.innerHTML = `
            <h3>Interview Completed</h3>
            <p>Score: <strong>${data.score}%</strong></p>
            <p>${data.summary || 'The interview has been saved.'}</p>
        `;
        chatMessages.appendChild(resultBox);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (error) {
        const resultBox = document.createElement('div');
        resultBox.style.textAlign = 'center';
        resultBox.style.padding = '1rem';
        resultBox.style.color = '#f87171';
        resultBox.innerHTML = `
            <h3>Interview Completed</h3>
            <p>We could not save the final score automatically.</p>
        `;
        chatMessages.appendChild(resultBox);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        console.error('Finalization failed:', error);
    }

    listenBtn.style.display = 'none';
    endBtn.style.display = 'none';
    shareBtn.style.display = 'none';

    if (cameraStream) {
        cameraStream.getTracks().forEach((track) => track.stop());
        cameraStream = null;
        webcam.srcObject = null;
        camStatus.className = 'status-badge status-off';
        camStatus.innerText = 'CAM OFF';
    }

    if (screenStream) {
        screenStream.getTracks().forEach((track) => track.stop());
        screenStream = null;
        screenPreview.srcObject = null;
        screenPreview.hidden = true;
        screenStatus.className = 'status-badge status-off';
        screenStatus.innerText = 'SCREEN OFF';
    }

    stopMicVisualization();
    logEvent('interview_completed_client', `Reason: ${reason}`);
}

function speak(text) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);

    utterance.onstart = () => {
        if (recognition) {
            recognition.abort();
        }
    };
    utterance.onend = () => {
        if (!finalized) {
            listenBtn.style.display = 'inline-block';
        }
    };
}

async function sendToAI(text) {
    const elapsedMinutes = startTime ? (Date.now() - startTime) / 60000 : 0;

    listenBtn.disabled = true;
    listenBtn.style.opacity = '0.5';
    listenBtn.innerText = 'AI IS THINKING...';

    let aiResponse = '';
    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: interviewToken,
                prompt: text,
                context: ollamaContext,
                elapsed_minutes: elapsedMinutes,
            }),
        });

        const data = await response.json();
        aiResponse = data.response || '';
        ollamaContext = data.context || ollamaContext;
    } catch (error) {
        console.error('Chat request failed:', error);
        aiResponse = 'Please continue and share a concrete example from your recent experience.';
    }

    const isConcluding = aiResponse.includes('[CONCLUDE]');
    if (isConcluding) {
        aiResponse = aiResponse.replace('[CONCLUDE]', '').trim();
    }

    listenBtn.disabled = false;
    listenBtn.style.opacity = '1';
    listenBtn.innerText = 'SPEAK NOW';

    if (aiResponse) {
        addMessage(aiResponse, 'ai');
        speak(aiResponse);

        if (isConcluding) {
            await finalizeInterview('ai_concluded');
        }
    }
}

function setupSpeechRecognition() {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = 'en-US';
        recognition.interimResults = false;

        recognition.onresult = (event) => {
            const transcriptText = event.results[0][0].transcript;
            addMessage(transcriptText, 'user');
            sendToAI(transcriptText);
            listenBtn.innerText = 'SPEAK NOW';
            listenBtn.style.opacity = '1';
        };

        recognition.onerror = (event) => {
            console.error('Speech Recognition error:', event.error);
            listenBtn.innerText = 'MIC ERROR - TRY AGAIN';
            logEvent('speech_error', event.error || 'Speech recognition error');
        };
    } else {
        setCheck('browser', checkBrowser, 'failed', 'Failed', 'Speech recognition unsupported');
        alert('Speech Recognition is not supported in this browser. Please use Chrome or Edge.');
    }
}

function wireSecurityMonitors() {
    document.addEventListener('visibilitychange', () => {
        if (!interviewStarted || finalized) {
            return;
        }
        if (document.hidden) {
            showWarning('Tab switch detected. Please keep the interview tab active.');
            logEvent('tab_hidden', 'Document became hidden');
        } else {
            hideWarning();
            logEvent('tab_visible', 'Document returned to visible');
        }
    });

    window.addEventListener('blur', () => {
        if (!interviewStarted || finalized) {
            return;
        }
        showWarning('Window focus lost. Please stay on the interview window.');
        logEvent('window_blur', 'Browser window lost focus');
    });

    window.addEventListener('focus', () => {
        if (!interviewStarted || finalized) {
            return;
        }
        hideWarning();
        logEvent('window_focus', 'Browser window focused');
    });

    document.addEventListener('fullscreenchange', enforceFullscreenState);
}

runCompatBtn.onclick = async () => {
    runCompatBtn.disabled = true;
    runCompatBtn.innerText = 'Running Tests...';
    try {
        await runCompatibilityChecks();
    } finally {
        runCompatBtn.disabled = false;
        runCompatBtn.innerText = 'Run All Tests';
    }
};

shareCompatBtn.onclick = async () => {
    await startScreenShare();
    updateControlState();
};

continueCompatBtn.onclick = async () => {
    if (!allChecksPass()) {
        showWarning('Please complete every check before proceeding.');
        return;
    }
    await enterInterviewPanel();
};

startBtn.onclick = async () => {
    if (!interviewEntered || !allChecksPass() || !cameraStream || !screenStream || !document.fullscreenElement) {
        showWarning('Please finish all checks and stay in fullscreen before starting.');
        return;
    }

    await markStarted();
    interviewStarted = true;
    startTime = Date.now();
    startBtn.style.display = 'none';
    endBtn.style.display = 'inline-block';

    const greeting = "Hello! I am your AI interviewer today. I'll be conducting this session for about 10 to 15 minutes. Can you please introduce yourself?";
    addMessage(greeting, 'ai');
    speak(greeting);
    logEvent('interview_question_started', 'Greeting delivered');
};

shareBtn.onclick = async () => {
    await startScreenShare();
};

listenBtn.onclick = () => {
    if (!recognition || finalized || !document.fullscreenElement) {
        showWarning('Please remain in fullscreen to continue speaking.');
        return;
    }
    listenBtn.innerText = 'LISTENING...';
    listenBtn.style.opacity = '0.5';
    recognition.start();
};

endBtn.onclick = async () => {
    await finalizeInterview('manual_end');
};

function init() {
    initMicMeter();
    setupSpeechRecognition();
    wireSecurityMonitors();
    runCompatibilityChecks();
    updateProgress();
    updateControlState();
}

init();
