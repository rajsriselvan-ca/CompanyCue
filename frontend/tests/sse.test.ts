import { describe, expect, it } from 'vitest';

import { SSEDecoder, readSSE } from '@/lib/sse';

describe('SSEDecoder', () => {
  it('parses a complete frame', () => {
    const decoder = new SSEDecoder();
    const frames = decoder.feed('id: 4\nevent: section_started\ndata: {"section":"news"}\n\n');

    expect(frames).toEqual([
      { id: '4', event: 'section_started', data: '{"section":"news"}', retry: undefined },
    ]);
  });

  it('reassembles a frame split across chunk boundaries', () => {
    const decoder = new SSEDecoder();

    expect(decoder.feed('event: stage\nda')).toEqual([]);
    expect(decoder.feed('ta: {"stage":"sea')).toEqual([]);
    const frames = decoder.feed('rching"}\n\n');

    expect(frames).toHaveLength(1);
    expect(JSON.parse(frames[0]!.data)).toEqual({ stage: 'searching' });
  });

  it('handles CRLF and bare CR line endings', () => {
    const decoder = new SSEDecoder();
    const frames = decoder.feed('event: a\r\ndata: 1\r\n\r\nevent: b\rdata: 2\r\r');

    expect(frames.map((frame) => frame.event)).toEqual(['a', 'b']);
  });

  it('joins multi-line data with newlines', () => {
    const decoder = new SSEDecoder();
    const [frame] = decoder.feed('data: line one\ndata: line two\n\n');

    expect(frame!.data).toBe('line one\nline two');
  });

  it('ignores heartbeat comments without emitting a frame', () => {
    const decoder = new SSEDecoder();

    expect(decoder.feed(': keep-alive\n\n')).toEqual([]);
    expect(decoder.feed('data: {"ok":true}\n\n')).toHaveLength(1);
  });

  it('strips exactly one leading space after the colon', () => {
    const decoder = new SSEDecoder();
    const [frame] = decoder.feed('data:  two spaces\n\n');

    expect(frame!.data).toBe(' two spaces');
  });

  it('reads the retry hint', () => {
    const decoder = new SSEDecoder();
    const [frame] = decoder.feed('retry: 3000\ndata: {}\n\n');

    expect(frame!.retry).toBe(3000);
  });

  it('treats a field with no colon as an empty value', () => {
    const decoder = new SSEDecoder();
    const [frame] = decoder.feed('data\nevent: ping\n\n');

    expect(frame).toEqual({ event: 'ping', id: undefined, data: '', retry: undefined });
  });

  it('flushes a trailing frame that never got its blank line', () => {
    const decoder = new SSEDecoder();

    expect(decoder.feed('event: last\ndata: {"a":1}')).toEqual([]);
    expect(decoder.finish()).toHaveLength(1);
  });

  it('strips a leading byte-order mark once', () => {
    const decoder = new SSEDecoder();
    const [frame] = decoder.feed('﻿data: hello\n\n');

    expect(frame!.data).toBe('hello');
  });
});

describe('readSSE', () => {
  function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
  }

  it('yields frames as chunks arrive', async () => {
    const frames = [];
    for await (const frame of readSSE(streamOf(['data: 1\n\n', 'data: 2\n\n']))) {
      frames.push(frame.data);
    }
    expect(frames).toEqual(['1', '2']);
  });

  it('keeps a multi-byte character split across chunks intact', async () => {
    const encoded = new TextEncoder().encode('data: café\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        // Split in the middle of the two-byte 'é'.
        controller.enqueue(encoded.slice(0, 10));
        controller.enqueue(encoded.slice(10));
        controller.close();
      },
    });

    const frames = [];
    for await (const frame of readSSE(stream)) frames.push(frame.data);
    expect(frames).toEqual(['café']);
  });
});
