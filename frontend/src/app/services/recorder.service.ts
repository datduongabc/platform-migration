import { Injectable } from '@angular/core';

export interface TrackInfo {
  hasMic: boolean;
  hasDisplayAudio: boolean;
}

export interface RecorderKit {
  recorder: MediaRecorder;
  getBlob: () => Blob;
  mimeType: string;
}

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

@Injectable({
  providedIn: 'root',
})
export class RecorderService {
  getSupportedMimeType(): string {
    if (typeof window === 'undefined' || !('MediaRecorder' in window)) return '';
    for (const type of PREFERRED_MIME_TYPES) {
      if (MediaRecorder.isTypeSupported(type)) return type;
    }
    return '';
  }

  checkRecordingSupport(): { supported: boolean; missingCapabilities: string[] } {
    if (typeof window === 'undefined') return { supported: false, missingCapabilities: [] };

    const missing: string[] = [];

    if (!navigator.mediaDevices?.getDisplayMedia) {
      missing.push('getDisplayMedia (screen/tab capture)');
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      missing.push('getUserMedia (microphone access)');
    }
    if (!('MediaRecorder' in window)) {
      missing.push('MediaRecorder API');
    } else if (!this.getSupportedMimeType()) {
      missing.push('supported audio recording codec (webm/ogg/mp4)');
    }

    return { supported: missing.length === 0, missingCapabilities: missing };
  }

  async startCapture(): Promise<{ micStream: MediaStream; displayStream: MediaStream }> {
    // Request microphone access
    const micStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });

    let displayStream: MediaStream;
    try {
      displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: true,
      });
    } catch (err) {
      micStream.getTracks().forEach((t) => t.stop());
      throw err;
    }

    // Stop video immediately as we only want tab/system audio
    displayStream.getVideoTracks().forEach((t) => t.stop());

    return { micStream, displayStream };
  }

  mixToMonoAudioStream(
    displayStream: MediaStream,
    micStream: MediaStream
  ): { mixedStream: MediaStream; hasDisplayAudio: boolean; audioContext: AudioContext } {
    const audioContext = new AudioContext();
    const destination = audioContext.createMediaStreamDestination();

    const displayAudioTracks = displayStream.getAudioTracks();
    const hasDisplayAudio = displayAudioTracks.length > 0;

    if (hasDisplayAudio) {
      const displayAudioOnly = new MediaStream(displayAudioTracks);
      const displaySource = audioContext.createMediaStreamSource(displayAudioOnly);
      displaySource.connect(destination);
    }

    const micSource = audioContext.createMediaStreamSource(micStream);
    micSource.connect(destination);

    return { mixedStream: destination.stream, hasDisplayAudio, audioContext };
  }

  createRecorder(mixedStream: MediaStream): RecorderKit {
    const mimeType = this.getSupportedMimeType();
    const recorder = new MediaRecorder(
      mixedStream,
      mimeType ? { mimeType } : undefined
    );
    const chunks: Blob[] = [];

    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    const getBlob = (): Blob =>
      new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });

    return { recorder, getBlob, mimeType: recorder.mimeType };
  }
}
