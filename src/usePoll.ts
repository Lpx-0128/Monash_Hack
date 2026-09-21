import { useEffect, useRef, useState } from "react";
import { RequestError } from "./api";

export function usePoll<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
) {
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const [state, setState] = useState<{
    data?: T;
    error?: Error;
    updated?: Date;
    loading: boolean;
  }>({ loading: true });
  const dataRef = useRef(state.data);
  dataRef.current = state.data;

  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout>,
      failures = 0;
    const controller = new AbortController();
    setState((old) => (old.data ? old : { loading: true }));

    const run = async () => {
      try {
        const data = await fetchRef.current(
          AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
        );
        if (!active) return;
        failures = 0;
        dataRef.current = data;
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
      if (active) {
        const current = dataRef.current as { workflow_status?: string } | undefined;
        const isProcessing = current && typeof current === "object" && current.workflow_status === "PROCESSING";
        const delay = isProcessing ? 600 : Math.min(3000 * 2 ** failures, 24000);
        timer = setTimeout(run, delay);
      }
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
      dataRef.current = data;
      setState({ data, loading: false, updated: new Date() });
    },
  };
}

