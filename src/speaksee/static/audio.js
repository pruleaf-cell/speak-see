// Microphone capture + PCM16 streaming to the app WebSocket.
// The mic device stays enabled after permission is granted, while audio streaming to the server
// is toggled per utterance (VAD/push-to-talk) to support "open the URL and speak".
(function () {
  const TARGET_SR = 16000;
  const PRE_ROLL_MS = 320; // audio we keep before VAD starts streaming

  function downsampleBuffer(buffer, inSampleRate, outSampleRate) {
    if (outSampleRate === inSampleRate) return buffer;
    const ratio = inSampleRate / outSampleRate;
    const newLen = Math.round(buffer.length / ratio);
    const out = new Float32Array(newLen);
    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < out.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
      let accum = 0, count = 0;
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
        accum += buffer[i];
        count++;
      }
      out[offsetResult] = count > 0 ? accum / count : 0;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    return out;
  }

  function floatTo16BitPCM(float32Array) {
    const out = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  class MicStreamer {
    constructor() {
      this.stream = null;
      this.audioCtx = null;
      this.source = null;
      this.processor = null;
      this.zeroGain = null;
      this.ws = null;
      this.onRms = null;

      this.enabled = false;   // device/audio graph active
      this.streaming = false; // sending audio to server

      this._preRoll = [];
      this._preRollBytes = 0;
      this._preRollMaxBytes = Math.floor((TARGET_SR * 2 * PRE_ROLL_MS) / 1000);
    }

    attachWebSocket(ws) {
      this.ws = ws;
    }

    async enable() {
      if (this.enabled) return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("getUserMedia not supported");
      }

      // Ask for permission once; keep the mic stream open for continuous RMS/VAD.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (this.audioCtx.state === "suspended") {
        try { await this.audioCtx.resume(); } catch (_) {}
      }
      this.source = this.audioCtx.createMediaStreamSource(this.stream);

      // ScriptProcessorNode is deprecated but widely supported and simplest for raw PCM.
      const bufferSize = 4096;
      this.processor = this.audioCtx.createScriptProcessor(bufferSize, 1, 1);

      this.processor.onaudioprocess = (e) => {
        if (!this.enabled || !this.audioCtx) return;
        const input = e.inputBuffer.getChannelData(0);

        // RMS for VAD/silence detection (handled in app.js).
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        if (this.onRms) {
          try { this.onRms(rms); } catch (_) {}
        }

        const down = downsampleBuffer(input, this.audioCtx.sampleRate, TARGET_SR);
        const pcm16 = floatTo16BitPCM(down);

        if (this.streaming && this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(pcm16.buffer);
        } else {
          // Keep a small pre-roll so we don't miss the first syllable when VAD triggers.
          this._preRoll.push(pcm16.buffer);
          this._preRollBytes += pcm16.byteLength;
          while (this._preRollBytes > this._preRollMaxBytes && this._preRoll.length > 0) {
            const b = this._preRoll.shift();
            if (b) this._preRollBytes -= b.byteLength || 0;
          }
        }
      };

      this.source.connect(this.processor);
      // Keep the processor alive without routing audio to speakers (avoid echo).
      this.zeroGain = this.audioCtx.createGain();
      this.zeroGain.gain.value = 0;
      this.processor.connect(this.zeroGain);
      this.zeroGain.connect(this.audioCtx.destination);

      this.enabled = true;
    }

    async disable() {
      await this.stopStreaming();
      if (!this.enabled) return;
      this.enabled = false;

      try { if (this.processor) this.processor.disconnect(); } catch (_) {}
      try { if (this.zeroGain) this.zeroGain.disconnect(); } catch (_) {}
      try { if (this.source) this.source.disconnect(); } catch (_) {}
      try { if (this.audioCtx) await this.audioCtx.close(); } catch (_) {}

      if (this.stream) {
        this.stream.getTracks().forEach((t) => t.stop());
      }

      this.stream = null;
      this.audioCtx = null;
      this.source = null;
      this.processor = null;
      this.zeroGain = null;
      this._preRoll = [];
      this._preRollBytes = 0;
    }

    async startStreaming() {
      if (this.streaming) return;
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) throw new Error("WebSocket not connected");
      if (!this.enabled) await this.enable();
      if (this.audioCtx && this.audioCtx.state === "suspended") {
        try { await this.audioCtx.resume(); } catch (_) {}
      }

      this.streaming = true;
      this.ws.send(JSON.stringify({ type: "audio_start", sample_rate: TARGET_SR, format: "pcm16", channels: 1 }));

      // Flush pre-roll (best-effort).
      try {
        for (const b of this._preRoll) {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(b);
        }
      } catch (_) {}
      this._preRoll = [];
      this._preRollBytes = 0;
    }

    async stopStreaming() {
      if (!this.streaming) return;
      this.streaming = false;
      try {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: "audio_stop" }));
        }
      } catch (_) {}
    }
  }

  window.SpeakSeeMic = { MicStreamer };
})();
