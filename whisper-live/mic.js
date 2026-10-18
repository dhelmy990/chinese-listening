// Batch microphone samples so the UI receives about 8 messages per second.
class Microphone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.used = 0;
    this.port.onmessage = event => {
      if (this.used) this.port.postMessage(this.buffer.slice(0, this.used));
      this.used = 0;
      this.port.postMessage(event.data === 'flush' ? 'flushed' : event.data);
    };
  }
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (samples) {
      for (const sample of samples) {
        this.buffer[this.used++] = sample;
        if (this.used === this.buffer.length) {
          this.port.postMessage(this.buffer.slice());
          this.used = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('microphone', Microphone);
