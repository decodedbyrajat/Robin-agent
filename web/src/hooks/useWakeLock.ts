import { useEffect, useRef, useCallback } from 'react';

/**
 * useWakeLock hook
 * 
 * Uses the Screen Wake Lock API to prevent the screen from sleeping.
 * It automatically requests a lock on mount and releases it on unmount.
 * It also handles visibility changes, re-requesting the lock when the
 * page becomes visible again.
 */
export function useWakeLock() {
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);

  const requestWakeLock = useCallback(async () => {
    if ('wakeLock' in navigator) {
      try {
        wakeLockRef.current = await navigator.wakeLock.request('screen');
        console.log('Screen Wake Lock is active');
        
        wakeLockRef.current.addEventListener('release', () => {
          console.log('Screen Wake Lock was released');
        });
      } catch (err: any) {
        console.error(`${err.name}, ${err.message}`);
      }
    }
  }, []);

  const releaseWakeLock = useCallback(() => {
    if (wakeLockRef.current) {
      void wakeLockRef.current.release();
      wakeLockRef.current = null;
    }
  }, []);

  useEffect(() => {
    void requestWakeLock();

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void requestWakeLock();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      releaseWakeLock();
    };
  }, [requestWakeLock, releaseWakeLock]);

  return { requestWakeLock, releaseWakeLock };
}
