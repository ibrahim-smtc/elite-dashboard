/**
 * Let a panel finish leaving before it stops existing.
 *
 * The drawer and the three modals are all mounted permanently by App and
 * guard themselves with `if (!isOpen) return null`. That is the whole reason
 * none of them has ever had an exit: the moment the flag flips, React removes
 * the markup, and there is nothing left to animate. So the entry drawer slides
 * in over 320ms and then blinks out of existence, which reads as the window
 * having been closed by something other than the person who closed it.
 *
 * This keeps the panel rendered for one animation after `isOpen` goes false,
 * flagging it `leaving` so the stylesheet can play the entrance backwards.
 *
 * It is a layout effect for the same reason ToastContainer is: an effect that
 * runs after paint would let the frame where the flag flips reach the screen
 * with the panel already gone - it would blink out, come back, and only then
 * animate away.
 *
 * Only transitions are acted on, so the first render of a closed panel does
 * not schedule a timer for a departure that never happened.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';

/* Must outlast --t-slow (320ms), or the panel is unmounted mid-exit. */
const EXIT_MS = 340;

export default function useClosing(isOpen, ms = EXIT_MS) {
  const [render, setRender] = useState(isOpen);
  const [leaving, setLeaving] = useState(false);
  const was = useRef(isOpen);
  const timer = useRef(0);

  useLayoutEffect(() => {
    if (isOpen === was.current) return;
    was.current = isOpen;
    clearTimeout(timer.current);

    if (isOpen) {
      setRender(true);
      setLeaving(false);
      return;
    }
    setLeaving(true);
    timer.current = setTimeout(() => {
      setRender(false);
      setLeaving(false);
    }, ms);
  }, [isOpen, ms]);

  useEffect(() => () => clearTimeout(timer.current), []);

  return { render, leaving };
}
