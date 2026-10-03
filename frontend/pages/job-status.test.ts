import {
  follow,
  isFinal,
  statusLine,
  type JobStatusConfig,
} from "./job-status";

const config: JobStatusConfig = {
  jobUrl: "https://example.org/geoapi/jobs/42?f=json",
  interval: 2000,
  labels: { running: "running", successful: "successful" },
  messages: { unreadable: "The status could not be read:" },
};

function reading(...states: object[]) {
  const queue = [...states];
  return vi.fn(async (_url: string, _init: RequestInit) => ({
    ok: true,
    status: 200,
    json: async () => queue.shift(),
  }));
}

describe("isFinal", () => {
  it.each([
    ["successful", true],
    ["failed", true],
    ["dismissed", true],
    ["running", false],
    ["accepted", false],
  ])("says %s is final: %s", (status, final) => {
    expect(isFinal(status)).toBe(final);
  });
});

describe("statusLine", () => {
  it("names the status in the page language, with progress and message", () => {
    expect(
      statusLine(
        { status: "running", progress: 60, message: "Halfway" },
        config.labels,
      ),
    ).toBe("running · 60% · Halfway");
  });
});

describe("follow", () => {
  it("reads the job until it ends, waiting between reads", async () => {
    const fetcher = reading(
      { status: "running", progress: 10 },
      { status: "running", progress: 60 },
      { status: "successful", progress: 100 },
    );
    const wait = vi.fn(async (_ms: number) => {});
    const seen: string[] = [];

    const last = await follow(
      config,
      (job) => seen.push(statusLine(job, config.labels)),
      fetcher,
      wait,
    );

    expect(last.status).toBe("successful");
    expect(seen).toEqual([
      "running · 10%",
      "running · 60%",
      "successful · 100%",
    ]);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(wait.mock.calls).toEqual([[2000], [2000]]);
  });

  it("stops at once when the job has already ended", async () => {
    const fetcher = reading({ status: "failed" });
    const wait = vi.fn(async (_ms: number) => {});

    await follow(config, () => {}, fetcher, wait);

    expect([fetcher.mock.calls.length, wait.mock.calls.length]).toEqual([1, 0]);
  });

  it("gives up when the job cannot be read", async () => {
    const fetcher = vi.fn(async (_url: string, _init: RequestInit) => ({
      ok: false,
      status: 404,
      json: async () => ({}),
    }));

    await expect(
      follow(
        config,
        () => {},
        fetcher,
        async () => {},
      ),
    ).rejects.toThrow("HTTP 404");
  });
});
