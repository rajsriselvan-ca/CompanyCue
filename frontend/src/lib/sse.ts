/**
 * A Server-Sent Events decoder that follows the WHATWG event-stream rules.
 *
 * The browser has `EventSource`, but it can only issue GET requests and gives
 * no way to abort cleanly, so research is a POST whose body we read ourselves.
 * That means owning the parse, and the parse has real edge cases:
 *
 * - Frames are separated by a blank line, and lines may end `\n`, `\r\n` or a
 *   bare `\r`. A chunk boundary can fall inside any of those sequences.
 * - `data:` accumulates across lines and is joined with `\n`; the single
 *   optional space after the colon is stripped, further spaces are content.
 * - Lines starting with `:` are comments — this is what heartbeats look like,
 *   and treating one as an event would corrupt the stream.
 * - A field with no colon is a field name with an empty value.
 */
import type { SSEFrame } from '@/lib/types';

export class SSEDecoder {
  private buffer = '';
  private startedStream = false;

  /** Feed a decoded text chunk; returns any frames it completed. */
  feed(chunk: string): SSEFrame[] {
    let text = chunk;
    if (!this.startedStream) {
      // A leading BOM is stripped once, per the spec.
      if (text.startsWith('﻿')) text = text.slice(1);
      this.startedStream = true;
    }
    this.buffer += text;

    const frames: SSEFrame[] = [];
    // Normalising line endings is safe here because a `\r` that turns out to be
    // the first half of a `\r\n` split across chunks still yields one break.
    this.buffer = this.buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    let boundary = this.buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const frame = parseBlock(block);
      if (frame) frames.push(frame);
      boundary = this.buffer.indexOf('\n\n');
    }
    return frames;
  }

  /**
   * Flush a final frame that arrived without its trailing blank line.
   * Servers should send one; a connection cut mid-flush means they did not.
   */
  finish(): SSEFrame[] {
    const remainder = this.buffer;
    this.buffer = '';
    const frame = remainder.trim() ? parseBlock(remainder.replace(/\n+$/, '')) : null;
    return frame ? [frame] : [];
  }
}

function parseBlock(block: string): SSEFrame | null {
  let event = 'message';
  let id: string | undefined;
  let retry: number | undefined;
  const dataLines: string[] = [];

  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) continue; // blank or comment

    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    switch (field) {
      case 'event':
        event = value;
        break;
      case 'data':
        dataLines.push(value);
        break;
      case 'id':
        // The spec says ignore an id containing NUL.
        if (!value.includes('\0')) id = value;
        break;
      case 'retry': {
        const parsed = Number.parseInt(value, 10);
        if (Number.isFinite(parsed)) retry = parsed;
        break;
      }
      default:
        break; // Unknown fields are ignored, not an error.
    }
  }

  // A block with only a `retry:` is still meaningful to a reconnecting client.
  if (dataLines.length === 0) {
    return retry === undefined ? null : { event, id, data: '', retry };
  }
  return { event, id, data: dataLines.join('\n'), retry };
}

/** Read a fetch response body and yield decoded frames as they arrive. */
export async function* readSSE(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SSEFrame> {
  const reader = body.getReader();
  const textDecoder = new TextDecoder();
  const decoder = new SSEDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // `stream: true` keeps a multi-byte character split across chunks intact.
      for (const frame of decoder.feed(textDecoder.decode(value, { stream: true }))) {
        yield frame;
      }
      if (signal?.aborted) return;
    }
    for (const frame of decoder.feed(textDecoder.decode())) yield frame;
    for (const frame of decoder.finish()) yield frame;
  } finally {
    // Releasing the lock lets the body be cancelled by the AbortController
    // instead of leaking a half-read stream when the component unmounts.
    reader.releaseLock();
  }
}
