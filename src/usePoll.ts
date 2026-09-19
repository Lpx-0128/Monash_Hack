import { useEffect, useRef, useState } from "react";
import { RequestError } from "./api";
export function usePoll<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
) {
  const epoch = useRef(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const [state, setState] = useState<{
    data?: T;
    error?: Error;
    updated?: Date;
    loading: boolean;
  }>({ loading: true });
  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout>,
      failures = 0;
    const controller = new AbortController();
    setState({ loading: true });
    const run = async () => {
      const started = epoch.current;
      try {
        const data = await fetchRef.current(
          AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
        );
        if (!active) return;
        failures = 0;
        if (started === epoch.current)
          setState({ data, loading: false, updated: new Date() });
      } catch (e) {
        if (!active) return;
        failures++;
        const error = e instanceof Error ? e : new Error("Request failed");
        setState((old) => ({
          ...(e instanceof RequestError && [401, 403, 404].includes(e.status)
            ? {}
            : old),
          error,
          loading: false,
        }));
        if (e instanceof RequestError && [401, 403, 404].includes(e.status))
          return;
      }
      if (active)
        timer = setTimeout(run, Math.min(3000 * 2 ** failures, 24000));
    };
    void run();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [key]);
  return {
    ...state,
    replace: (data: T) => {
      epoch.current++;
      setState({ data, loading: false, updated: new Date() });
    },
  };
}
