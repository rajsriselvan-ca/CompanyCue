import { SSEDecoder } from '@/lib/sse';

describe('SSEDecoder', () => {
  it('reassembles events split across network chunks', () => {
    const decoder = new SSEDecoder();

    expect(decoder.feed('id: 1\nevent: section_')).toEqual([]);
    expect(decoder.feed('started\ndata: {"section":"overview"}\n\n')).toEqual([
      {
        id: '1',
        event: 'section_started',
        data: { section: 'overview' },
      },
    ]);
  });

  it('parses multiple events and ignores heartbeat comments', () => {
    const decoder = new SSEDecoder();
    const events = decoder.feed(
      ': keep-alive\n\nevent: section_progress\ndata: {"received_characters":120}\n\n' +
        'event: research_completed\ndata: {"report":{"id":"r-1"}}\n\n',
    );

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ event: 'section_progress', data: { received_characters: 120 } });
    expect(events[1]).toMatchObject({ event: 'research_completed', data: { report: { id: 'r-1' } } });
  });

  it('returns a safe message when an event contains malformed JSON', () => {
    const decoder = new SSEDecoder();
    expect(decoder.feed('event: research_failed\ndata: service unavailable\n\n')).toEqual([
      {
        id: undefined,
        event: 'research_failed',
        data: { message: 'service unavailable' },
      },
    ]);
  });
});
