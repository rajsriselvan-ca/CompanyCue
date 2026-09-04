import type { StreamEvent } from '@/lib/briefd-types';

export class SSEDecoder {
  private buffer = '';

  feed(chunk: string): StreamEvent[] {
    this.buffer += chunk.replaceAll('\r\n', '\n');
    const events: StreamEvent[] = [];
    let boundary = this.buffer.indexOf('\n\n');

    while (boundary >= 0) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const parsed = this.parseBlock(block);
      if (parsed) events.push(parsed);
      boundary = this.buffer.indexOf('\n\n');
    }

    return events;
  }

  finish(): StreamEvent[] {
    const trailing = this.buffer.trim();
    this.buffer = '';
    const parsed = trailing ? this.parseBlock(trailing) : null;
    return parsed ? [parsed] : [];
  }

  private parseBlock(block: string): StreamEvent | null {
    if (!block || block.startsWith(':')) return null;

    let event = 'message';
    let id: string | undefined;
    const dataLines: string[] = [];

    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
      if (field === 'event') event = value;
      if (field === 'id') id = value;
      if (field === 'data') dataLines.push(value);
    }

    if (dataLines.length === 0) return null;
    const serialized = dataLines.join('\n');

    try {
      return { id, event, data: JSON.parse(serialized) as Record<string, unknown> };
    } catch {
      return { id, event, data: { message: serialized } };
    }
  }
}

export async function* readSSEStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = stream.getReader();
  const textDecoder = new TextDecoder();
  const decoder = new SSEDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decoder.feed(textDecoder.decode(value, { stream: true }))) {
        yield event;
      }
    }
    for (const event of decoder.feed(textDecoder.decode())) yield event;
    for (const event of decoder.finish()) yield event;
  } finally {
    reader.releaseLock();
  }
}
