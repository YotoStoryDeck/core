import { state } from './state.js';
import { BrokerApi } from './broker-api.js';
import { ScreensaverScreen } from './screens/screensaver.js';

export const timersMixin = {
  /**
   * Returns true if current wall-clock time falls within the configured bedtime window.
   */
  isBedtimeNow() {
    const bedtimeStr = state.parentSettings.bedtime || '19:00';
    const wakeTimeStr = state.parentSettings.wakeTime || '07:00';
    const [bH, bM] = bedtimeStr.split(':').map(Number);
    const [wH, wM] = wakeTimeStr.split(':').map(Number);
    const bMinutes = bH * 60 + bM;
    const wMinutes = wH * 60 + wM;
    const now = new Date();
    const curMinutes = now.getHours() * 60 + now.getMinutes();
    if (bMinutes > wMinutes) {
      // Overnight schedule (e.g. 19:00 -> 07:00)
      return (curMinutes >= bMinutes || curMinutes < wMinutes);
    } else {
      // Same-day schedule
      return (curMinutes >= bMinutes && curMinutes < wMinutes);
    }
  },
  /**
   * Evaluates if sleep timer should arm or reset upon playback state change or setting modification.
   */
  checkAndArmSleepTimer(forceReset = false) {
    const mins = state.parentSettings.sleepTimerMin || 0;
    if (mins <= 0) {
      state.sleepTimerRemainingSec = 0;
      return;
    }
    const mode = state.parentSettings.sleepTimerMode || 'bedtime';
    const shouldArm = (mode === 'always') || this.isBedtimeNow();
    if (!shouldArm) {
      state.sleepTimerRemainingSec = 0;
      return;
    }
    const isPlaying = Boolean(state.isPlaying || state.activeDevice?.is_playing);
    if (isPlaying) {
      if (forceReset || state.sleepTimerRemainingSec <= 0) {
        state.sleepTimerRemainingSec = mins * 60;
        console.log(`[SleepTimer] Armed for ${mins} minutes (${state.sleepTimerRemainingSec}s)`);
      }
    } else if (!isPlaying && forceReset) {
      state.sleepTimerRemainingSec = 0;
    }
  },
  /**
   * Starts 1Hz sleep timer countdown ticker.
   */
  /**
   * Tracks user interaction across the kiosk frame and triggers the night-clock screensaver upon inactivity.
   */
  startInactivityTracker() {
    this._lastActivityTime = Date.now();
    const onUserActivity = () => {
      this._lastActivityTime = Date.now();
      // If currently on screensaver, wake up on any interaction
      if (state.screen === 'screensaver') {
        this.exitScreensaver();
      }
    };
    // Attach listeners on both window and document for full kiosk coverage
    ['pointerdown', 'touchstart', 'mousedown', 'keydown'].forEach(evt => {
      window.addEventListener(evt, onUserActivity, { passive: true });
    });
  },
  /**
   * Evaluates inactivity against parentSettings.screensaverMin.
   */
  checkInactivity() {
    const saverMin = state.parentSettings.screensaverMin ?? 10;
    if (saverMin <= 0) return; // 0 = off
    // Do not trigger screensaver if already active, offline, or inside pin / grownups portal
    if (state.screen === 'screensaver' || state.screen === 'offline' || state.screen === 'pin' || state.screen === 'grownups') {
      return;
    }
    const idleMs = Date.now() - (this._lastActivityTime || Date.now());
    const thresholdMs = saverMin * 60 * 1000;
    if (idleMs >= thresholdMs) {
      this.enterScreensaver();
    }
  },
  enterScreensaver() {
    console.log('[Screensaver] Inactivity threshold reached. Transitioning to Night Clock.');
    state.saverPreviousScreen = state.screen || 'profile';
    state.setScreen('screensaver');
    this.render();
  },
  exitScreensaver() {
    console.log('[Screensaver] Waking from Night Clock.');
    this._lastActivityTime = Date.now();
    const returnTo = state.saverPreviousScreen || 'profile';
    state.saverPreviousScreen = null;
    state.setScreen(returnTo);
    this.render();
  },
  startSleepTimerTicker() {
    if (this._sleepTicker) return;
    this._sleepTicker = setInterval(() => {
      // Check inactivity for screensaver transition
      this.checkInactivity();
      // If screensaver is actively displaying, update clock in-place (no full DOM wipe or flashing)
      if (state.screen === 'screensaver') {
        if (!ScreensaverScreen.tick()) {
          this.render();
        }
      }
      const isPlaying = Boolean(state.isPlaying || state.activeDevice?.is_playing);
      if (!isPlaying) {
        return;
      }
      // Safety Gate 1: Never arm or stop an away/traveling player
      if (state.activeDevice && state.activeDevice.is_home === false) {
        if (state.sleepTimerRemainingSec > 0) {
          console.warn(`[SleepTimer] Active player ${state.activeDevice.name} is AWAY from home. Sleep timer aborted.`);
          state.sleepTimerRemainingSec = 0;
        }
        return;
      }
      // Safety Gate 2: Never stop an external session not initiated on this controller
      if (!state.localSessionActive) {
        return;
      }
      const mins = state.parentSettings.sleepTimerMin || 0;
      if (mins <= 0) {
        state.sleepTimerRemainingSec = 0;
        return;
      }
      const mode = state.parentSettings.sleepTimerMode || 'bedtime';
      if (mode === 'bedtime' && !this.isBedtimeNow()) {
        state.sleepTimerRemainingSec = 0;
        return;
      }
      if (state.sleepTimerRemainingSec > 0) {
        state.sleepTimerRemainingSec--;
        if (state.sleepTimerRemainingSec === 0) {
          console.log('[SleepTimer] Timer reached 0! Stopping player playback...');
          state.setPlaying(false);
          state.localSessionActive = false;
          this.render();
          BrokerApi.sendPlayerControl('stop').then(res => {
            console.log('[SleepTimer] Stop command executed:', res);
          });
        }
      } else if (state.sleepTimerRemainingSec <= 0 && isPlaying) {
        // Arm if playback began during active window on this controller
        this.checkAndArmSleepTimer(false);
      }
    }, 1000);
  }
};
