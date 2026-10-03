import { readConfig } from "./config";

export interface JobStatusConfig {
  jobUrl: string;
  interval: number;
  labels: Record<string, string>;
  messages: Record<string, string>;
}

export interface JobState {
  status: string;
  progress?: number | null;
  message?: string | null;
}

interface Answer {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type Fetch = (url: string, init: RequestInit) => Promise<Answer>;

const FINAL = new Set(["successful", "failed", "dismissed"]);

/** Whether a job in ``status`` has stopped for good. */
export function isFinal(status: string): boolean {
  return FINAL.has(status);
}

/** The status in the page language, with the progress and the message when the job has them. */
export function statusLine(
  job: JobState,
  labels: Record<string, string>,
): string {
  const parts = [labels[job.status] ?? job.status];
  if (typeof job.progress === "number") {
    parts.push(`${job.progress}%`);
  }
  if (job.message) {
    parts.push(job.message);
  }
  return parts.join(" · ");
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Reads the job until it ends, reporting each state; resolves with the last one. */
export async function follow(
  config: JobStatusConfig,
  report: (job: JobState) => void,
  fetcher: Fetch = fetch,
  wait: (ms: number) => Promise<void> = pause,
): Promise<JobState> {
  for (;;) {
    const answer = await fetcher(config.jobUrl, {
      headers: { Accept: "application/json" },
    });
    if (!answer.ok) {
      throw new Error(`HTTP ${answer.status}`);
    }
    const job = (await answer.json()) as JobState;
    report(job);
    if (isFinal(job.status)) {
      return job;
    }
    await wait(config.interval);
  }
}

class JobStatus extends HTMLElement {
  connectedCallback(): void {
    const config = readConfig<JobStatusConfig>(this);
    const line = document.createElement("p");
    line.className = "status";
    line.setAttribute("aria-live", "polite");
    this.append(line);
    follow(config, (job) => {
      line.textContent = statusLine(job, config.labels);
    })
      // The page of a finished job shows its end and its results.
      .then(() => window.location.reload())
      .catch((error: unknown) => {
        line.textContent = `${config.messages.unreadable} ${String(error)}`;
        line.classList.add("error");
      });
  }
}

if (!customElements.get("fga-job-status")) {
  customElements.define("fga-job-status", JobStatus);
}
