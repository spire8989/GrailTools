/* global window */

(function exposeAudioSynth(global) {
  "use strict";

  const MUSIC_WAVES = new Set(["sine", "triangle", "square", "sawtooth"]);
  const SFX_WAVES = new Set([...MUSIC_WAVES, "noise"]);
  const NOTE_SEMITONES = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

  function noteFrequency(note) {
    const match = typeof note === "string" && note.trim().match(/^([A-Ga-g])([#b]?)(-?\d+)$/);
    if (!match) throw new Error(`Invalid note name ${String(note)}.`);
    const accidental = match[2] === "#" ? 1 : match[2] === "b" ? -1 : 0;
    const midi = (Number(match[3]) + 1) * 12 + NOTE_SEMITONES[match[1].toUpperCase()] + accidental;
    if (!Number.isInteger(midi) || midi < 0 || midi > 127) throw new Error(`Note ${note} is outside the supported MIDI range.`);
    return 440 * (2 ** ((midi - 69) / 12));
  }

  function numberOr(value, fallback) {
    return Number.isFinite(Number(value)) ? Number(value) : fallback;
  }

  function safeStop(node, when) {
    try { node.stop(when); } catch (_error) { /* Already stopped. */ }
  }

  class SynthPlayer {
    constructor() {
      this.context = null;
      this.master = null;
      this.volume = 0.7;
      this.music = null;
      this.sfx = null;
      this.musicRequest = 0;
      this.sfxRequest = 0;
    }

    async ensureContext() {
      if (!this.context) {
        const AudioContextClass = global.AudioContext || global.webkitAudioContext;
        if (!AudioContextClass) throw new Error("This browser does not provide the Web Audio API.");
        this.context = new AudioContextClass();
        this.master = this.context.createGain();
        this.master.gain.value = this.volume;
        this.master.connect(this.context.destination);
      }
      if (this.context.state === "suspended") await this.context.resume();
      return this.context;
    }

    setVolume(value) {
      this.volume = Math.max(0, Math.min(1, numberOr(value, this.volume)));
      if (this.master && this.context) {
        this.master.gain.setTargetAtTime(this.volume, this.context.currentTime, 0.01);
      }
    }

    status() {
      return {
        music: this.music ? (this.music.paused ? "paused" : "playing") : "stopped",
        sfx: Boolean(this.sfx),
        volume: this.volume,
      };
    }

    async playMusic(definition) {
      return this._beginMusic(definition, 0);
    }

    async resumeMusic() {
      if (!this.music?.paused) return false;
      const definition = this.music.definition;
      const positionBeat = this.music.positionBeat;
      return this._beginMusic(definition, positionBeat);
    }

    async restartMusic() {
      return this.playMusic(this.music?.definition);
    }

    pauseMusic() {
      const music = this.music;
      if (!music || music.paused) return false;
      const elapsed = Math.max(0, (this.context?.currentTime || 0) - music.anchorTime);
      music.positionBeat = (elapsed / music.secondsPerBeat) % music.definition.loopBeats;
      music.paused = true;
      this._clearMusicTimer(music);
      this._stopNodes(music.nodes);
      return true;
    }

    stopMusic() {
      this.musicRequest += 1;
      if (!this.music) return;
      this._clearMusicTimer(this.music);
      this._stopNodes(this.music.nodes);
      this.music = null;
    }

    async playSfx(definition) {
      this.stopSfx();
      const request = this.sfxRequest;
      const context = await this.ensureContext();
      if (request !== this.sfxRequest) return false;
      if (!definition || !Array.isArray(definition.layers)) throw new Error("SFX definition has no layers to play.");
      const state = { definition, nodes: new Set(), timer: null };
      this.sfx = state;
      const startTime = context.currentTime + 0.03;
      definition.layers.forEach((layer) => this._scheduleSfxLayer(state, layer, startTime));
      state.timer = global.setTimeout(() => {
        if (this.sfx === state) this.stopSfx();
      }, Math.max(80, (numberOr(definition.duration, 0.1) + 0.3) * 1000));
      return true;
    }

    stopSfx() {
      this.sfxRequest += 1;
      if (!this.sfx) return;
      if (this.sfx.timer !== null) global.clearTimeout(this.sfx.timer);
      this._stopNodes(this.sfx.nodes);
      this.sfx = null;
    }

    stopAll() {
      this.stopMusic();
      this.stopSfx();
    }

    async _beginMusic(definition, positionBeat) {
      this.stopMusic();
      if (!definition || !Array.isArray(definition.voices)) throw new Error("Music definition has no voices to play.");
      const request = this.musicRequest;
      const context = await this.ensureContext();
      if (request !== this.musicRequest) return false;
      const bpm = numberOr(definition.bpm, 80);
      const loopBeats = numberOr(definition.loopBeats, 1);
      const secondsPerBeat = 60 / bpm;
      const loopSeconds = loopBeats * secondsPerBeat;
      const offset = Math.max(0, Math.min(loopBeats, numberOr(positionBeat, 0))) % loopBeats;
      const state = {
        definition,
        nodes: new Set(),
        timer: null,
        paused: false,
        positionBeat: offset,
        secondsPerBeat,
        loopSeconds,
        anchorTime: context.currentTime + 0.03 - offset * secondsPerBeat,
        nextLoop: 0,
      };
      this.music = state;
      this._scheduleMusicLoop(state);
      return true;
    }

    _scheduleMusicLoop(state) {
      if (this.music !== state || state.paused) return;
      const context = this.context;
      const loopStart = state.anchorTime + state.nextLoop * state.loopSeconds;
      const loopEnd = loopStart + state.loopSeconds;
      const now = context.currentTime;
      state.nextLoop += 1;
      state.definition.voices.forEach((voice) => {
        if (!voice || !MUSIC_WAVES.has(voice.wave || "sine")) return;
        (Array.isArray(voice.notes) ? voice.notes : []).forEach((note) => {
          if (!Array.isArray(note) || note.length < 3) return;
          const noteStart = loopStart + numberOr(note[1], 0) * state.secondsPerBeat;
          const noteEnd = noteStart + numberOr(note[2], 0) * state.secondsPerBeat;
          if (noteEnd <= now + 0.01 || noteStart >= loopEnd + 0.01) return;
          const scheduledStart = Math.max(noteStart, now + 0.02);
          if (noteEnd <= scheduledStart) return;
          this._scheduleOscillator(state, voice.wave || "sine", note[0], voice.gain, voice.attack, voice.release, scheduledStart, noteEnd);
        });
      });
      const delay = Math.max(35, (loopEnd - context.currentTime - 0.12) * 1000);
      state.timer = global.setTimeout(() => this._scheduleMusicLoop(state), delay);
    }

    _scheduleSfxLayer(state, layer, baseTime) {
      if (!layer || !SFX_WAVES.has(layer.wave || "sine")) return;
      const start = baseTime + Math.max(0, numberOr(layer.start, 0));
      const duration = Math.max(0.001, numberOr(layer.duration, state.definition.duration));
      const end = start + duration;
      if (layer.wave === "noise") {
        this._scheduleNoise(state, layer, start, end);
      } else {
        this._scheduleOscillator(state, layer.wave || "sine", layer.startHz, layer.gain, layer.attack, layer.release, start, end, layer.endHz);
      }
    }

    _scheduleOscillator(state, wave, pitchOrHz, gain, attack, release, start, end, endHz = null) {
      const context = this.context;
      end = Math.max(end, start + 0.001);
      let startHz;
      try {
        startHz = typeof pitchOrHz === "number" ? pitchOrHz : noteFrequency(pitchOrHz);
      } catch (_error) {
        return;
      }
      if (!Number.isFinite(startHz) || startHz <= 0) return;
      const oscillator = context.createOscillator();
      oscillator.type = wave;
      oscillator.frequency.setValueAtTime(startHz, start);
      if (endHz !== null && Number.isFinite(Number(endHz)) && Number(endHz) > 0) {
        oscillator.frequency.exponentialRampToValueAtTime(Number(endHz), end);
      }
      const envelope = context.createGain();
      const level = Math.max(0, Math.min(1, numberOr(gain, 0.1)));
      const length = Math.max(0.001, end - start);
      const attackTime = Math.min(Math.max(0, numberOr(attack, 0)), length * 0.45);
      const releaseTime = Math.min(Math.max(0, numberOr(release, 0)), length * 0.45);
      const releaseStart = Math.max(start + attackTime, end - releaseTime);
      envelope.gain.setValueAtTime(0, start);
      if (attackTime > 0) envelope.gain.linearRampToValueAtTime(level, start + attackTime);
      else envelope.gain.setValueAtTime(level, start);
      envelope.gain.setValueAtTime(level, releaseStart);
      if (releaseTime > 0) envelope.gain.linearRampToValueAtTime(0, end + releaseTime);
      else envelope.gain.setValueAtTime(0, end);
      oscillator.connect(envelope);
      envelope.connect(this.master);
      const record = { node: oscillator, envelope, start };
      state.nodes.add(record);
      oscillator.onended = () => {
        state.nodes.delete(record);
        try { oscillator.disconnect(); envelope.disconnect(); } catch (_error) { /* Already disconnected. */ }
      };
      oscillator.start(start);
      safeStop(oscillator, end + releaseTime + 0.02);
    }

    _scheduleNoise(state, layer, start, end) {
      const context = this.context;
      end = Math.max(end, start + 0.001);
      const duration = Math.max(0.001, end - start);
      const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * duration), context.sampleRate);
      const samples = buffer.getChannelData(0);
      for (let index = 0; index < samples.length; index += 1) samples[index] = Math.random() * 2 - 1;
      const source = context.createBufferSource();
      source.buffer = buffer;
      const envelope = context.createGain();
      const level = Math.max(0, Math.min(1, numberOr(layer.gain, 0.1)));
      const attackTime = Math.min(Math.max(0, numberOr(layer.attack, 0)), duration * 0.45);
      const releaseTime = Math.min(Math.max(0, numberOr(layer.release, 0)), duration * 0.45);
      const releaseStart = Math.max(start + attackTime, end - releaseTime);
      envelope.gain.setValueAtTime(0, start);
      if (attackTime > 0) envelope.gain.linearRampToValueAtTime(level, start + attackTime);
      else envelope.gain.setValueAtTime(level, start);
      envelope.gain.setValueAtTime(level, releaseStart);
      if (releaseTime > 0) envelope.gain.linearRampToValueAtTime(0, end + releaseTime);
      else envelope.gain.setValueAtTime(0, end);
      source.connect(envelope);
      envelope.connect(this.master);
      const record = { node: source, envelope, start };
      state.nodes.add(record);
      source.onended = () => {
        state.nodes.delete(record);
        try { source.disconnect(); envelope.disconnect(); } catch (_error) { /* Already disconnected. */ }
      };
      source.start(start);
      safeStop(source, end + releaseTime + 0.02);
    }

    _clearMusicTimer(music) {
      if (music.timer !== null) {
        global.clearTimeout(music.timer);
        music.timer = null;
      }
    }

    _stopNodes(nodes) {
      if (!nodes) return;
      const when = this.context ? this.context.currentTime : 0;
      nodes.forEach((record) => safeStop(record.node, Math.max(when, numberOr(record.start, when))));
      nodes.clear();
    }
  }

  global.GrailAudioSynth = {
    SynthPlayer,
    noteFrequency,
    MUSIC_WAVES: [...MUSIC_WAVES],
    SFX_WAVES: [...SFX_WAVES],
  };
})(window);
