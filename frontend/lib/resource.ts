"use client";

import { useEffect, useState } from "react";

type Result<T> = { data: T; error?: never } | { data?: never; error: unknown };

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<{ load: typeof load; attempt: number; result: Result<T> }>();

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setSettled({ load, attempt, result: { data } }); },
      (error: unknown) => { if (!controller.signal.aborted) setSettled({ load, attempt, result: { error } }); },
    );
    return () => controller.abort();
  }, [load, attempt]);

  const result = settled?.load === load && settled.attempt === attempt ? settled.result : undefined;
  return { data: result?.data, error: result?.error, pending: !result, retry: () => setAttempt((value) => value + 1) };
}
