const chatContainer = document.getElementById("chatContainer");
const micButton = document.getElementById("micButton");
const textInput = document.getElementById("textInput");
const sendButton = document.getElementById("sendButton");
const statusBar = document.getElementById("statusBar");
const replyAudio = document.getElementById("replyAudio");
const playPauseButton = document.getElementById("playPauseButton");
const newProblemButton = document.getElementById("newProblemButton");

const sessionId = (() => {
  const existing = localStorage.getItem("tutor_session_id");
  if (existing) return existing;
  const fresh = "session-" + Math.random().toString(36).slice(2) + Date.now();
  localStorage.setItem("tutor_session_id", fresh);
  return fresh;
})();

let ttsProvider = "elevenlabs"; // overwritten by /api/config on load
fetch("/api/config")
  .then((res) => res.json())
  .then((cfg) => { ttsProvider = cfg.tts_provider; })
  .catch((err) => console.error("Failed to load /api/config:", err));

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.textContent = text;
  chatContainer.appendChild(div);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return div;
}

// Adds a "Continue" button right after a given message bubble, so the
// student can reveal the next held-back stage of a staged solution. Removes
// itself once clicked (a fresh one is added after the next stage if more
// remain).
function addContinueButton(afterMessageDiv) {
  const btn = document.createElement("button");
  btn.className = "continue-button";
  btn.textContent = "Continue ➜";
  btn.addEventListener("click", () => requestContinue(btn));
  afterMessageDiv.insertAdjacentElement("afterend", btn);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return btn;
}

function setStatus(text) {
  statusBar.textContent = text;
}

// --- Pause/Play control for the currently playing reply --------------------
let isUsingBrowserTts = false;
let currentUtterance = null;

function showPlayPauseButton() {
  playPauseButton.hidden = false;
  playPauseButton.textContent = "⏸️";
  playPauseButton.title = "Pause voice";
}

function hidePlayPauseButton() {
  playPauseButton.hidden = true;
}

function setPlayPauseToPaused() {
  playPauseButton.textContent = "▶️";
  playPauseButton.title = "Play voice";
}

function setPlayPauseToPlaying() {
  playPauseButton.textContent = "⏸️";
  playPauseButton.title = "Pause voice";
}

playPauseButton.addEventListener("click", () => {
  if (isUsingBrowserTts) {
    if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
      window.speechSynthesis.pause();
      setPlayPauseToPaused();
    } else if (window.speechSynthesis.paused) {
      window.speechSynthesis.resume();
      setPlayPauseToPlaying();
    }
    return;
  }
  if (replyAudio.paused) {
    replyAudio.play();
    setPlayPauseToPlaying();
  } else {
    replyAudio.pause();
    setPlayPauseToPaused();
  }
});

function speakInBrowser(replyText) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) {
      console.warn("Browser SpeechSynthesis not supported.");
      resolve();
      return;
    }
    isUsingBrowserTts = true;
    window.speechSynthesis.cancel(); // stop any previous utterance
    const utterance = new SpeechSynthesisUtterance(replyText);
    utterance.lang = "en-IN";
    utterance.rate = 0.95;
    const finish = () => {
      isUsingBrowserTts = false;
      currentUtterance = null;
      resolve();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    currentUtterance = utterance;
    showPlayPauseButton();
    setPlayPauseToPlaying();
    window.speechSynthesis.speak(utterance);
  });
}

async function fetchChunkAudioUrl(chunkText) {
  const res = await fetch("/api/chat/speak_chunk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: chunkText }),
  });
  if (!res.ok) throw new Error("TTS chunk request failed");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

function playAudioUrl(url) {
  return new Promise((resolve) => {
    const cleanupAndResolve = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    replyAudio.src = url;
    replyAudio.onended = cleanupAndResolve;
    replyAudio.onerror = cleanupAndResolve;
    replyAudio.play().then(() => {
      showPlayPauseButton();
      setPlayPauseToPlaying();
    }).catch(cleanupAndResolve);
  });
}

// Incremented every time a new stage starts playing, so an older,
// still-running playReplyChunks loop can detect it's been superseded (e.g.
// the student clicked Continue before the previous stage finished narrating)
// and stop cleanly instead of fighting the new stage for the shared <audio>
// element / speechSynthesis queue.
let playbackGeneration = 0;

function stopCurrentPlayback() {
  playbackGeneration++; // any in-flight loop will see this and bail out
  if (isUsingBrowserTts) {
    window.speechSynthesis.cancel();
  } else {
    replyAudio.pause();
  }
  hidePlayPauseButton();
}

// Plays speech chunks back-to-back. While chunk N is playing, chunk N+1's
// audio is already being fetched in the background (pipelined), so there's
// minimal gap between chunks instead of one long wait before any audio starts.
async function playReplyChunks(chunks) {
  if (!chunks || chunks.length === 0) return;
  const myGeneration = ++playbackGeneration;

  if (ttsProvider === "browser") {
    // Browser SpeechSynthesis has no per-request latency to hide, so just
    // speak the joined text as one utterance.
    await speakInBrowser(chunks.join(" "));
    if (myGeneration === playbackGeneration) hidePlayPauseButton();
    return;
  }

  try {
    let nextAudioPromise = fetchChunkAudioUrl(chunks[0]);
    for (let i = 0; i < chunks.length; i++) {
      const audioUrl = await nextAudioPromise;
      if (myGeneration !== playbackGeneration) return; // superseded — stop silently
      if (i + 1 < chunks.length) {
        nextAudioPromise = fetchChunkAudioUrl(chunks[i + 1]); // prefetch next while this one plays
      }
      await playAudioUrl(audioUrl);
    }
    if (myGeneration === playbackGeneration) hidePlayPauseButton();
  } catch (err) {
    if (myGeneration === playbackGeneration) {
      hidePlayPauseButton();
      console.error("Audio playback failed:", err);
      setStatus("Reply ready (audio unavailable)");
    }
  }
}

async function sendText(message) {
  if (attachedImageFile) {
    await sendImage(attachedImageFile, message);
    return;
  }
  if (!message.trim()) return;
  addMessage("user", message);
  textInput.value = "";
  const pending = addMessage("assistant", "Priya Ma'am is thinking...");
  pending.classList.add("pending");
  setStatus("Thinking...");

  try {
    const res = await fetch("/api/chat/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    pending.classList.remove("pending");
    pending.textContent = data.reply_text;
    // Show Continue immediately (text is ready) rather than waiting for the
    // full audio narration to finish — the student can read ahead and
    // continue without being blocked by playback length.
    if (data.has_more_stages) addContinueButton(pending);
    setStatus("Speaking...");
    await playReplyChunks(data.speech_chunks);
    setStatus("");
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = "Sorry, something went wrong. Please try again.";
    setStatus("Error — please retry");
    console.error(err);
  }
}

// Sends an uploaded diagram/graph image, with an optional caption typed in
// the same text box. Mirrors sendText/sendVoice's pending-bubble pattern.
async function sendImage(imageFile, caption) {
  const userBubbleText = caption && caption.trim() ? caption : "(uploaded a diagram)";
  addMessage("user", userBubbleText);
  clearAttachedImage();
  textInput.value = "";

  const pending = addMessage("assistant", "Priya Ma'am is looking at your diagram...");
  pending.classList.add("pending");
  setStatus("Analyzing image...");

  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("image", imageFile, imageFile.name || "diagram.jpg");
  formData.append("caption", caption || "");

  try {
    const res = await fetch("/api/chat/image", { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    pending.classList.remove("pending");
    pending.textContent = data.reply_text;
    if (data.has_more_stages) addContinueButton(pending);
    setStatus("Speaking...");
    await playReplyChunks(data.speech_chunks);
    setStatus("");
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = "Sorry, something went wrong with the image. Please try again.";
    setStatus("Error — please retry");
    console.error(err);
  }
}

// Reveals the next held-back stage of a staged solution. Removes the
// clicked Continue button immediately (so it can't be double-clicked while
// the request is in flight), stops any audio still narrating the previous
// stage, appends the next stage as a new assistant message, plays its
// audio, and adds a fresh Continue button if more stages remain after this one.
async function requestContinue(button) {
  button.remove();
  stopCurrentPlayback();
  const pending = addMessage("assistant", "Priya Ma'am is continuing...");
  pending.classList.add("pending");
  setStatus("Thinking...");

  try {
    const res = await fetch("/api/chat/continue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    if (!data.reply_text) {
      // Nothing was actually pending (e.g. stale button after a reset) —
      // quietly remove the placeholder instead of showing an empty bubble.
      pending.remove();
      setStatus("");
      return;
    }

    pending.classList.remove("pending");
    pending.textContent = data.reply_text;
    if (data.has_more_stages) addContinueButton(pending);
    setStatus("Speaking...");
    await playReplyChunks(data.speech_chunks);
    setStatus("");
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = "Sorry, something went wrong. Please try again.";
    setStatus("Error — please retry");
    console.error(err);
  }
}

async function sendVoice(audioBlob) {
  const pendingUser = addMessage("user", "🎙️ (transcribing...)");
  pendingUser.classList.add("pending");
  setStatus("Transcribing your question...");

  const extension = audioBlob.type.includes("ogg") ? "ogg" : "webm";
  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("audio", audioBlob, `question.${extension}`);

  try {
    const res = await fetch("/api/chat/voice", { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    pendingUser.classList.remove("pending");
    pendingUser.textContent = data.transcript || "(could not transcribe)";

    const pendingReply = addMessage("assistant", "Priya Ma'am is thinking...");
    pendingReply.classList.add("pending");
    setStatus("Thinking...");

    pendingReply.classList.remove("pending");
    pendingReply.textContent = data.reply_text;
    if (data.has_more_stages) addContinueButton(pendingReply);
    setStatus("Speaking...");
    await playReplyChunks(data.speech_chunks);
    setStatus("");
  } catch (err) {
    pendingUser.classList.remove("pending");
    pendingUser.textContent = "(voice message failed to send)";
    setStatus("Error — please retry");
    console.error(err);
  }
}

sendButton.addEventListener("click", () => sendText(textInput.value));
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendText(textInput.value);
});

// --- Push-to-talk mic recording -------------------------------------------
let mediaRecorder = null;
let audioChunks = [];

// Explicit codec so the Blob's declared type always matches what was
// actually encoded — letting the browser pick a default and then relabeling
// the Blob as a fixed "audio/webm" risks a mismatch Sarvam's parser rejects.
const _PREFERRED_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
];
const _RECORDER_MIME_TYPE = _PREFERRED_MIME_TYPES.find(
  (type) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(type)
);

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = _RECORDER_MIME_TYPE
      ? new MediaRecorder(stream, { mimeType: _RECORDER_MIME_TYPE })
      : new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
    mediaRecorder.onstop = () => {
      const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      stream.getTracks().forEach((track) => track.stop());
      sendVoice(audioBlob);
    };
    mediaRecorder.start();
    micButton.classList.add("recording");
    setStatus("Listening... release to send");
  } catch (err) {
    console.error("Mic access failed:", err);
    setStatus("Microphone access denied or unavailable");
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  micButton.classList.remove("recording");
}

// Mouse (desktop) — hold to talk
micButton.addEventListener("mousedown", startRecording);
micButton.addEventListener("mouseup", stopRecording);
micButton.addEventListener("mouseleave", () => {
  if (mediaRecorder && mediaRecorder.state === "recording") stopRecording();
});

// Touch (mobile) — hold to talk
micButton.addEventListener("touchstart", (e) => {
  e.preventDefault();
  startRecording();
});
micButton.addEventListener("touchend", (e) => {
  e.preventDefault();
  stopRecording();
});

// --- Side panels: Notepad & Calculator (mutually exclusive) ---------------
const notepadButton = document.getElementById("notepadButton");
const notepadPanel = document.getElementById("notepadPanel");
const notepadTextarea = document.getElementById("notepadTextarea");
const notepadCloseButton = document.getElementById("notepadCloseButton");
const notepadClearButton = document.getElementById("notepadClearButton");

const calculatorButton = document.getElementById("calculatorButton");
const calculatorPanel = document.getElementById("calculatorPanel");
const calculatorCloseButton = document.getElementById("calculatorCloseButton");
const calcDisplay = document.getElementById("calcDisplay");

const NOTEPAD_STORAGE_KEY = "tutor_notepad_content";

function closeAllPanels() {
  notepadPanel.hidden = true;
  calculatorPanel.hidden = true;
  notepadButton.classList.remove("active");
  calculatorButton.classList.remove("active");
}

function toggleNotepad() {
  const willOpen = notepadPanel.hidden;
  closeAllPanels();
  if (willOpen) {
    notepadPanel.hidden = false;
    notepadButton.classList.add("active");
    notepadTextarea.focus();
  }
}

function toggleCalculator() {
  const willOpen = calculatorPanel.hidden;
  closeAllPanels();
  if (willOpen) {
    calculatorPanel.hidden = false;
    calculatorButton.classList.add("active");
  }
}

notepadButton.addEventListener("click", toggleNotepad);
calculatorButton.addEventListener("click", toggleCalculator);
notepadCloseButton.addEventListener("click", closeAllPanels);
calculatorCloseButton.addEventListener("click", closeAllPanels);

// Notepad: persist to localStorage as the student types.
notepadTextarea.value = localStorage.getItem(NOTEPAD_STORAGE_KEY) || "";
notepadTextarea.addEventListener("input", () => {
  localStorage.setItem(NOTEPAD_STORAGE_KEY, notepadTextarea.value);
});
notepadClearButton.addEventListener("click", () => {
  notepadTextarea.value = "";
  localStorage.removeItem(NOTEPAD_STORAGE_KEY);
  notepadTextarea.focus();
});

// --- Calculator (basic arithmetic) -----------------------------------------
// Hand-rolled tokenizer + recursive-descent parser for +,-,*,/ with standard
// precedence, rather than evaluating the expression string via eval/Function.
let calcExpression = "";

function calcFormatDisplay(expr) {
  // Show the operator symbols students expect (×, ÷) instead of the raw
  // characters (*, /) used internally for evaluation.
  return expr.replace(/\*/g, "×").replace(/\//g, "÷") || "0";
}

function calcUpdateDisplay() {
  calcDisplay.value = calcFormatDisplay(calcExpression);
}

function calcTokenize(expr) {
  const tokens = [];
  const re = /\d+\.?\d*|\.\d+|[+\-*/]/g;
  let match;
  while ((match = re.exec(expr)) !== null) {
    tokens.push(match[0]);
  }
  return tokens;
}

// Recursive-descent parser: expression := term (('+'|'-') term)*
//                           term       := number (('*'|'/') number)*
function calcParseAndEvaluate(expr) {
  const tokens = calcTokenize(expr);
  let pos = 0;

  function parseTerm() {
    let value = parseFloat(tokens[pos++]);
    if (Number.isNaN(value)) throw new Error("Invalid number");
    while (tokens[pos] === "*" || tokens[pos] === "/") {
      const op = tokens[pos++];
      const next = parseFloat(tokens[pos++]);
      if (Number.isNaN(next)) throw new Error("Invalid number");
      value = op === "*" ? value * next : value / next;
    }
    return value;
  }

  function parseExpression() {
    let value = parseTerm();
    while (tokens[pos] === "+" || tokens[pos] === "-") {
      const op = tokens[pos++];
      const next = parseTerm();
      value = op === "+" ? value + next : value - next;
    }
    return value;
  }

  if (tokens.length === 0) throw new Error("Empty expression");
  const result = parseExpression();
  if (pos !== tokens.length) throw new Error("Unexpected trailing tokens");
  return result;
}

function calcEvaluate() {
  if (!calcExpression) return;
  try {
    const result = calcParseAndEvaluate(calcExpression);
    if (typeof result !== "number" || !isFinite(result)) throw new Error("bad result");
    calcExpression = String(Math.round(result * 1e10) / 1e10);
  } catch {
    calcExpression = "";
    calcDisplay.value = "Error";
    return;
  }
  calcUpdateDisplay();
}

document.querySelectorAll(".calc-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.calc;
    if (key === "clear") {
      calcExpression = "";
    } else if (key === "backspace") {
      calcExpression = calcExpression.slice(0, -1);
    } else if (key === "=") {
      calcEvaluate();
      return;
    } else if (key === "sqrt") {
      try {
        const value = calcParseAndEvaluate(calcExpression || "0");
        calcExpression = String(Math.sqrt(value));
      } catch {
        calcExpression = "";
      }
    } else if (key === "percent") {
      try {
        const value = calcParseAndEvaluate(calcExpression || "0");
        calcExpression = String(value / 100);
      } catch {
        calcExpression = "";
      }
    } else {
      calcExpression += key;
    }
    calcUpdateDisplay();
  });
});

// --- "New" button: explicitly move on from the current problem -------------
// Discards any held-back stages of the problem the student is mid-solving
// (server-side, via /new_problem) WITHOUT resetting conversation history, and
// removes any visible Continue button so the chat doesn't dangle a stale
// invitation to continue a problem the student has chosen to leave behind.
newProblemButton.addEventListener("click", async () => {
  document.querySelectorAll(".continue-button").forEach((btn) => btn.remove());
  stopCurrentPlayback();
  try {
    await fetch("/api/chat/new_problem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (err) {
    console.error("Failed to start new problem:", err);
  }
  addMessage("assistant", "Sari kanna, sollunga — adha podunga, vera ennoda doubt?");
  textInput.focus();
});

// --- (+) Image attach: diagrams/graphs (v2) --------------------------------
const attachImageButton = document.getElementById("attachImageButton");
const imageFileInput = document.getElementById("imageFileInput");
const imagePreviewBar = document.getElementById("imagePreviewBar");
const imagePreviewThumb = document.getElementById("imagePreviewThumb");
const imagePreviewName = document.getElementById("imagePreviewName");
const imagePreviewRemoveButton = document.getElementById("imagePreviewRemoveButton");

const MAX_IMAGE_BYTES = 8 * 1024 * 1024; // keep in sync with backend's _MAX_IMAGE_BYTES
let attachedImageFile = null;
let attachedImagePreviewUrl = null;

function clearAttachedImage() {
  attachedImageFile = null;
  if (attachedImagePreviewUrl) {
    URL.revokeObjectURL(attachedImagePreviewUrl);
    attachedImagePreviewUrl = null;
  }
  imageFileInput.value = "";
  imagePreviewBar.hidden = true;
}

function setAttachedImage(file) {
  attachedImageFile = file;
  if (attachedImagePreviewUrl) URL.revokeObjectURL(attachedImagePreviewUrl);
  attachedImagePreviewUrl = URL.createObjectURL(file);
  imagePreviewThumb.src = attachedImagePreviewUrl;
  imagePreviewName.textContent = file.name || "diagram.jpg";
  imagePreviewBar.hidden = false;
  textInput.placeholder = "Add a question about this diagram (optional)...";
  textInput.focus();
}

attachImageButton.addEventListener("click", () => imageFileInput.click());

imageFileInput.addEventListener("change", () => {
  const file = imageFileInput.files && imageFileInput.files[0];
  if (!file) return;
  if (file.size > MAX_IMAGE_BYTES) {
    setStatus("Image too large (max 8MB) — please choose a smaller photo.");
    imageFileInput.value = "";
    return;
  }
  setAttachedImage(file);
});

imagePreviewRemoveButton.addEventListener("click", () => {
  clearAttachedImage();
  textInput.placeholder = "Type your doubt here... (English or Tanglish)";
});
