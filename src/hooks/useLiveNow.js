import { useEffect, useState } from "react";

export function useLiveNow(enabled = true) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const update = () => setNow(Date.now());
    update();
    if (!enabled) return undefined;
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  return now;
}
