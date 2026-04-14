const webcam = document.getElementById('webcam');
const chatMessages = document.getElementById('chatMessages');
const warningBanner = document.getElementById('warningBanner');
const startBtn = document.getElementById('startBtn');
const listenBtn = document.getElementById('listenBtn');
const endBtn = document.getElementById('endBtn');
const chatComposer = document.getElementById('chatComposer');
const chatInput = document.getElementById('chatInput');
const camStatus = document.getElementById('camStatus');
const micStatus = document.getElementById('micStatus');

const interviewToken = window.INTERVIEW_TOKEN;
const transcript = [];

let recognition;
let aiContext = [];
let startTime = null;
let finalized = false;
let interviewStarted = false;
let cameraStream = null;

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
    if (!warningBanner) return;
    warningBanner.hidden = false;
    warningBanner.textContent = message;
}

function hideWarning() {
    if (!warningBanner) return;
    warningBanner.hidden = true;
    warningBanner.textContent = '';
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

async function startCameraAndMic() {
    if (!navigator.mediaDevices?.getUserMedia) {
        showWarning('Camera and microphone access is not supported in this browser.');
        return false;
    }

    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true,
        });
        webcam.srcObject = cameraStream;
        if (camStatus) camStatus.innerText = 'CAM ON';
        if (micStatus) micStatus.innerText = 'MIC ON';
        return true;
    } catch (error) {
        console.error('Camera/mic access denied:', error);
        if (camStatus) camStatus.innerText = 'CAM OFF';
        if (micStatus) micStatus.innerText = 'MIC OFF';
        showWarning('Please allow camera and microphone access to continue.');
        return false;
    }
}

async function finalizeInterview(reason) {
    if (finalized) return;
    finalized = true;
    interviewStarted = false;

    if (recognition) {
        try {
            recognition.abort();
        } catch (error) {
            console.warn('Unable to abort speech recognition:', error);
        }
    }

    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }

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
        console.error('Finalization failed:', error);
    }

    listenBtn.style.display = 'none';
    endBtn.style.display = 'none';

    if (cameraStream) {
        cameraStream.getTracks().forEach((track) => track.stop());
        cameraStream = null;
        webcam.srcObject = null;
        if (camStatus) camStatus.innerText = 'CAM OFF';
        if (micStatus) micStatus.innerText = 'MIC OFF';
    }
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
    if (finalized || !interviewStarted) {
        return;
    }

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
                context: aiContext,
                elapsed_minutes: elapsedMinutes,
            }),
        });

        const data = await response.json();
        aiResponse = data.response || '';
        aiContext = data.context || aiContext;
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

    if (aiResponse && !finalized) {
        addMessage(aiResponse, 'ai');
        speak(aiResponse);

        if (isConcluding) {
            await finalizeInterview('ai_concluded');
        }
    }
}

async function sendTypedMessage() {
    if (!chatInput || finalized || !interviewStarted) {
        return;
    }
    const text = chatInput.value.trim();
    if (!text) {
        return;
    }

    chatInput.value = '';
    addMessage(text, 'user');
    await sendToAI(text);
}

function setupSpeechRecognition() {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = 'en-US';
        recognition.interimResults = false;

        recognition.onresult = (event) => {
            if (finalized || !interviewStarted) {
                return;
            }
            const transcriptText = event.results[0][0].transcript;
            addMessage(transcriptText, 'user');
            sendToAI(transcriptText);
            listenBtn.innerText = 'SPEAK NOW';
            listenBtn.style.opacity = '1';
        };

        recognition.onerror = (event) => {
            if (finalized) {
                return;
            }
            console.error('Speech Recognition error:', event.error);
            listenBtn.innerText = 'MIC ERROR - TRY AGAIN';
        };
    } else {
        showWarning('Speech Recognition is not supported in this browser. Please use Chrome or Edge.');
    }
}

startBtn.onclick = async () => {
    if (finalized) {
        return;
    }

    const cameraReady = await startCameraAndMic();
    if (!cameraReady) {
        return;
    }

    await markStarted();
    interviewStarted = true;
    startTime = Date.now();
    startBtn.style.display = 'none';
    endBtn.style.display = 'inline-block';
    hideWarning();

    const greeting = "Hello! I am your AI interviewer today. I'll be conducting this session for about 10 to 15 minutes. Can you please introduce yourself?";
    addMessage(greeting, 'ai');
    speak(greeting);
};

listenBtn.onclick = () => {
    if (!recognition || finalized || !interviewStarted) {
        showWarning('Speech recognition is not ready yet.');
        return;
    }
    listenBtn.innerText = 'LISTENING...';
    listenBtn.style.opacity = '0.5';
    recognition.start();
};

if (chatComposer) {
    chatComposer.addEventListener('submit', async (event) => {
        event.preventDefault();
        await sendTypedMessage();
    });
}

if (chatInput) {
    chatInput.addEventListener('keydown', async (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            await sendTypedMessage();
        }
    });
}

endBtn.onclick = async () => {
    if (finalized) {
        window.location.href = '/';
        return;
    }

    try {
        await finalizeInterview('manual_end');
    } finally {
        window.location.href = '/';
    }
};

function init() {
    setupSpeechRecognition();
}

init();
