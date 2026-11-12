"use client";

import { useRef } from "react";

export function useWriteKey() {
  const keys = useRef(new Map<string, string>());
  return {
    key(scope: string, body: unknown) {
      const identity = JSON.stringify([scope, body]);
      const existing = keys.current.get(identity);
      if (existing) return existing;
      const key = crypto.randomUUID();
      keys.current.set(identity, key);
      return key;
    },
    complete(scope: string, body: unknown) {
      keys.current.delete(JSON.stringify([scope, body]));
    },
  };
}
