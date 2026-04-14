const waitingCountdown = document.getElementById('countdownText');
const waitingTitle = document.getElementById('waitingTitle');
const waitingMessage = document.getElementById('waitingMessage');
const enterInterviewLink = document.getElementById('enterInterviewLink');
const secondsUntilStart = Number(window.SECONDS_UNTIL_START || 0);
const interviewTime = new Date(window.INTERVIEW_TIME);

function updateWaitingRoom() {
    const remaining = Math.max(0, Math.ceil((interviewTime.getTime() - Date.now()) / 1000));
    if (waitingCountdown) {
        waitingCountdown.textContent = remaining > 0 ? `${remaining}s` : 'Ready now';
    }

    if (remaining > 0) {
        if (waitingTitle) waitingTitle.textContent = 'You are early for the interview';
        if (waitingMessage) {
            waitingMessage.textContent = 'Please stay on this page. You can run the System Compatibility Check while you wait.';
        }
        if (enterInterviewLink) {
            enterInterviewLink.setAttribute('aria-disabled', 'true');
            enterInterviewLink.setAttribute('tabindex', '-1');
            enterInterviewLink.classList.add('is-disabled');
        }
    } else {
        if (waitingTitle) waitingTitle.textContent = 'You can enter the interview now';
        if (waitingMessage) {
            waitingMessage.textContent = 'The interview is ready. You can continue to the interview room now.';
        }
        if (enterInterviewLink) {
            enterInterviewLink.removeAttribute('aria-disabled');
            enterInterviewLink.removeAttribute('tabindex');
            enterInterviewLink.classList.remove('is-disabled');
        }
    }
}

updateWaitingRoom();
setInterval(updateWaitingRoom, 1000);
