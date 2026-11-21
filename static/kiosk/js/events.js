import { state } from './state.js';
import { BrokerApi } from './broker-api.js';

export const eventsMixin = {
  bindEvents() {
    this.container.addEventListener('change', (e) => {
      const guLockSelect = e.target.closest('[data-act="gu-select-lock-player"]');
      if (guLockSelect) {
        const did = guLockSelect.value;
        const allPlayers = state.getAllAvailablePlayers();
        const found = allPlayers.find(p => p.id === did);
        if (found) {
          state.setActiveDevice(found);
          state.lockedPlayerId = found.id;
          state.persistParentSettings();
          this.syncActiveDevicePlayback();
        }
      }
    });
    this.container.addEventListener('click', (e) => {
      // 0. Dismiss screensaver on any tap/click
      if (state.screen === 'screensaver') {
        this.exitScreensaver();
        return;
      }
      // 1. Profile Card Selection
      const card = e.target.closest('[data-profile]');
      if (card) {
        this.selectProfile(card.dataset.profile);
        return;
      }
      // 2. Profile Switcher Pill
      const switcher = e.target.closest('[data-act="switch-profile"]');
      if (switcher) {
        state.setScreen('profile');
        this.render();
        return;
      }
      // 2b. Device Picker Toggle
      const devToggle = e.target.closest('[data-act="toggle-device-picker"]');
      if (devToggle) {
        state.toggleDevicePicker();
        this.render();
        return;
      }
      // 2c. Target Device Selection
      const devOpt = e.target.closest('[data-act="select-device"]');
      if (devOpt) {
        const did = devOpt.dataset.deviceId;
        const target = (state.activeProfile?.players || []).find(p => p.id === did);
        if (target) {
          state.setActiveDevice(target);
          this.syncActiveDevicePlayback();
          this.render();
        }
        return;
      }
      // Close device picker if clicking elsewhere
      if (state.isDevicePickerOpen && !e.target.closest('.device-pill-wrap')) {
        state.isDevicePickerOpen = false;
        this.render();
      }
      // 3. Catalog Tab Navigation (All / Series / ABS / Yoto)
      const tab = e.target.closest('.tab-btn[data-tab]');
      if (tab && state.screen === 'catalog') {
        state.setActiveTab(tab.dataset.tab);
        this.render();
        return;
      }
      // 4. Media Card Selection (Catalog Grid)
      const tile = e.target.closest('[data-card]');
      if (tile) {
        const id = tile.dataset.card;
        const found = state.catalog.find(c => (c.id || c.cardId) === id);
        if (found) {
          state.setPreviewCard(found);
          // If no active card is playing, also set state.card
          if (!state.card || !state.isPlaying) {
            state.setCard(found);
          }
          state.setScreen('detail');
          this.render();
          // Fetch real tracklist / chapters from Broker if not yet cached on the card
          if (!found.chapters || found.chapters.length === 0) {
            BrokerApi.fetchMediaTracks(id).then(tracks => {
              if (tracks && tracks.length > 0) {
                found.chapters = tracks.map(t => ({
                  key: t.key || '',
                  track_key: t.track_key || t.key || '',
                  title: t.title,
                  duration: t.duration_seconds || 0,
                  icon_url: t.icon_url
                }));
                found.duration = tracks.reduce((sum, t) => sum + (t.duration_seconds || 0), 0);
                if (state.card && (state.card.id || state.card.cardId) === id) {
                  state.card = { ...found };
                  this.render();
                }
              }
            });
          }
        }
        return;
      }
      // Change PIN button inside Grown-ups screen
      const guChangePin = e.target.closest('[data-act="gu-change-pin"]');
      if (guChangePin) {
        state.previousScreen = 'grownups';
        state.currentEnteredPin = '';
        state.isPinError = false;
        state.pinMode = 'change';
        state.setScreen('pin');
        this.render();
        return;
      }
      // PIN Cancel Button
      const pinCancel = e.target.closest('[data-act="pin-cancel"]');
      if (pinCancel) {
        const returnScreen = state.previousScreen || (state.mode === 'standalone' ? 'catalog' : 'profile');
        state.previousScreen = null;
        state.currentEnteredPin = '';
        state.isPinError = false;
        state.setScreen(returnScreen);
        this.render();
        return;
      }
      // PIN Keypad Tap
      const pinKeyBtn = e.target.closest('.pin-key');
      if (pinKeyBtn && state.screen === 'pin') {
        const key = pinKeyBtn.dataset.key;
        if (key === 'clear') {
          state.currentEnteredPin = '';
          state.isPinError = false;
          this.render();
          return;
        }
        if (key === 'back') {
          state.currentEnteredPin = (state.currentEnteredPin || '').slice(0, -1);
          state.isPinError = false;
          this.render();
          return;
        }
        if (key != null && (state.currentEnteredPin || '').length < 4) {
          state.currentEnteredPin = (state.currentEnteredPin || '') + key;
          state.isPinError = false;
          this.render();
          // Check if 4 digits reached
          if (state.currentEnteredPin.length === 4) {
            const entered = state.currentEnteredPin;
            setTimeout(() => {
              if (state.pinMode === 'unlock') {
                if (entered === state.parentPin) {
                  state.currentEnteredPin = '';
                  state.failedPinAttempts = 0;
                  state.setScreen('grownups');
                  this.render();
                } else {
                  state.isPinError = true;
                  state.currentEnteredPin = '';
                  state.failedPinAttempts = (state.failedPinAttempts || 0) + 1;
                  
                  if (state.failedPinAttempts >= 3) {
                    state.pinLockoutUntil = Date.now() + 10000; // 10 second penalty delay
                    this.render();
                    const lockoutInterval = setInterval(() => {
                      if (Date.now() >= state.pinLockoutUntil) {
                        clearInterval(lockoutInterval);
                        state.pinLockoutUntil = 0;
                        state.failedPinAttempts = 0;
                        state.isPinError = false;
                        this.render();
                      } else {
                        this.render();
                      }
                    }, 1000);
                  } else {
                    this.render();
                    setTimeout(() => {
                      state.isPinError = false;
                      this.render();
                    }, 400);
                  }
                }
              } else if (state.pinMode === 'setup') {
                state.tempSetupPin = entered;
                state.currentEnteredPin = '';
                state.pinMode = 'confirm';
                this.render();
              } else if (state.pinMode === 'confirm') {
                if (entered === state.tempSetupPin) {
                  state.parentPin = entered;
                  state.persistParentSettings();
                  state.tempSetupPin = '';
                  state.currentEnteredPin = '';
                  state.setScreen('grownups');
                  this.render();
                } else {
                  state.isPinError = true;
                  state.currentEnteredPin = '';
                  this.render();
                  setTimeout(() => {
                    state.pinMode = 'setup';
                    state.isPinError = false;
                    this.render();
                  }, 500);
                }
              } else if (state.pinMode === 'change') {
                if (entered === state.parentPin) {
                  state.currentEnteredPin = '';
                  state.pinMode = 'setup';
                  this.render();
                } else {
                  state.isPinError = true;
                  state.currentEnteredPin = '';
                  this.render();
                  setTimeout(() => {
                    state.isPinError = false;
                    this.render();
                  }, 400);
                }
              }
            }, 100);
          }
        }
        return;
      }
      // Grown-ups Tab Navigation
      const guTabBtn = e.target.closest('[data-act="gu-tab"]');
      if (guTabBtn) {
        state.guActiveTab = guTabBtn.dataset.tab;
        this.render();
        return;
      }
      // Grown-ups Close Button
      const guClose = e.target.closest('[data-act="gu-close"]');
      if (guClose) {
        const returnScreen = state.previousScreen || (state.mode === 'standalone' ? 'catalog' : 'profile');
        state.previousScreen = null;
        state.setScreen(returnScreen);
        this.render();
        return;
      }
      // Grown-ups Mode Switch
      const guModeBtn = e.target.closest('[data-act="gu-set-mode"]');
      if (guModeBtn) {
        const newMode = guModeBtn.dataset.mode;
        state.mode = newMode;
        state.persistParentSettings();
        if (newMode === 'standalone') {
          // Switch directly to catalog without profile requirement
          const allPlayers = state.getAllAvailablePlayers();
          if (!state.activeDevice && allPlayers.length > 0) {
            state.setActiveDevice(allPlayers[0]);
          }
          if (state.profiles.length > 0) {
            BrokerApi.fetchLiveCatalog(state.profiles[0].id).then(() => {
              this.syncActiveDevicePlayback();
            });
          }
        }
        this.render();
        return;
      }
      // Grown-ups Lock Player Toggle
      const guLockBtn = e.target.closest('[data-act="gu-set-lock"]');
      if (guLockBtn) {
        state.lockPlayer = (guLockBtn.dataset.lock === 'true');
        if (state.lockPlayer && state.activeDevice) {
          state.lockedPlayerId = state.activeDevice.id;
        }
        state.persistParentSettings();
        this.render();
        return;
      }
      // Grown-ups Sleep Timer Duration
      const guSleepBtn = e.target.closest('[data-act="gu-set-sleep"]');
      if (guSleepBtn) {
        state.parentSettings.sleepTimerMin = parseInt(guSleepBtn.dataset.val, 10);
        state.persistParentSettings();
        this.checkAndArmSleepTimer(true);
        this.render();
        return;
      }
      // Grown-ups Sleep Timer Scope (Bedtime vs Always)
      const guSleepScopeBtn = e.target.closest('[data-act="gu-set-sleep-scope"]');
      if (guSleepScopeBtn) {
        state.parentSettings.sleepTimerMode = guSleepScopeBtn.dataset.val;
        state.persistParentSettings();
        this.checkAndArmSleepTimer(true);
        this.render();
        return;
      }
      // Grown-ups Remote/Travel Block Toggle
      const guRemoteBlockBtn = e.target.closest('[data-act="gu-set-remote-block"]');
      if (guRemoteBlockBtn) {
        state.blockRemotePlayback = (guRemoteBlockBtn.dataset.val === 'true');
        state.persistParentSettings();
        this.render();
        return;
      }
      // Grown-ups Screensaver Delay
      const guSaverBtn = e.target.closest('[data-act="gu-set-saver"]');
      if (guSaverBtn) {
        state.parentSettings.screensaverMin = parseInt(guSaverBtn.dataset.val, 10);
        state.persistParentSettings();
        this.render();
        return;
      }
      // Grown-ups Clock Size
      const guClockSizeBtn = e.target.closest('[data-act="gu-set-clock-size"]');
      if (guClockSizeBtn) {
        state.parentSettings.clockSize = parseInt(guClockSizeBtn.dataset.val, 10);
        state.persistParentSettings();
        this.render();
        return;
      }
      // Grown-ups Restart Action
      const guRestartBtn = e.target.closest('[data-act="gu-restart"]');
      if (guRestartBtn) {
        if (confirm("Restart this controller?")) {
          window.location.reload();
        }
        return;
      }
      // Grown-ups Re-pair Action
      const guRepairBtn = e.target.closest('[data-act="gu-re-pair"]');
      if (guRepairBtn) {
        state.deviceToken = null;
        state.setScreen('profile');
        this.bootstrap();
        return;
      }
      // 4b. Inspect Active Card (Tap Cover or Title in Player Screen)
      const inspectCard = e.target.closest('[data-act="inspect-card"]');
      if (inspectCard) {
        if (state.card) {
          state.setPreviewCard(state.card);
          state.setScreen('detail');
          this.render();
          // Fetch tracks if needed
          const id = state.card.id || state.card.cardId;
          if (id && (!state.card.chapters || state.card.chapters.length === 0)) {
            BrokerApi.fetchMediaTracks(id).then(tracks => {
              if (tracks && tracks.length > 0) {
                state.card.chapters = tracks.map(t => ({
                  key: t.key || '',
                  track_key: t.track_key || t.key || '',
                  title: t.title,
                  duration: t.duration_seconds || 0,
                  icon_url: t.icon_url
                }));
                state.card.duration = tracks.reduce((sum, t) => sum + (t.duration_seconds || 0), 0);
                state.previewCard = { ...state.card };
                this.render();
              }
            });
          }
        }
        return;
      }
      // 5. Quick Action Button inside Nowbar (play/pause toggle should NOT navigate)
      const nbPlayBtn = e.target.closest('.nb-play');
      if (nbPlayBtn) {
        const nextState = !state.isPlaying;
        state.setPlaying(nextState);
        this.render();
        const targetAction = nextState ? 'resume' : 'pause';
        BrokerApi.sendPlayerControl(targetAction).then(res => {
          if (!res || !res.ok) {
            console.warn(`Failed to execute ${targetAction}, reverting UI state:`, res);
            state.setPlaying(!nextState);
            this.render();
          }
        });
        return;
      }
      // 5b. Back / Screen Navigation Links
      const go = e.target.closest('[data-go]');
      if (go) {
        state.setScreen(go.dataset.go);
        this.render();
        return;
      }
      // 6. Track / Chapter Row Tap -> Play
      const chrow = e.target.closest('[data-ch]');
      if (chrow) {
        const chIdx = +chrow.dataset.ch;
        const targetCard = state.previewCard || state.card;
        this.initiatePlayback(targetCard, chIdx, chrow);
        return;
      }
      // 7. Player Action Controls
      const actBtn = e.target.closest('[data-act]');
      const act = actBtn?.dataset.act;
      if (act) {
        // Prevent clicking nowbar play from opening the now screen
        if (act === 'toggle' && actBtn.classList.contains('nb-play')) {
          e.stopPropagation();
        }
        if (act === 'playstart') {
          const btn = document.getElementById('btn-play-book') || actBtn;
          const targetCard = state.previewCard || state.card;
          const isSameActive = Boolean(
            state.isPlaying && state.card && targetCard && (
              (targetCard.id && (state.card.id === targetCard.id || state.card.cardId === targetCard.id)) ||
              (targetCard.title && state.card.title === targetCard.title)
            )
          );
          if (isSameActive) {
            state.setScreen('now');
            this.render();
            return;
          }
          // Pass null for chapterIndex so 'Play Book' resumes where the profile/player left off
          this.initiatePlayback(targetCard, null, btn);
          return;
        }
        if (act === 'toggle') {
          const nextState = !state.isPlaying;
          state.setPlaying(nextState);
          this.render();
          const targetAction = nextState ? 'resume' : 'pause';
          BrokerApi.sendPlayerControl(targetAction).then(res => {
            if (!res || !res.ok) {
              console.warn(`Failed to execute ${targetAction}, reverting UI state:`, res);
              state.setPlaying(!nextState);
              this.render();
            }
          });
          return;
        }
        if (act === 'next') {
          BrokerApi.sendPlayerControl('next').then(res => {
            if (res && res.ok) {
              if (state.card && state.chapterIndex < (state.card.chapters || []).length - 1) {
                state.setChapter(state.chapterIndex + 1);
              }
              BrokerApi.getDeviceConfig().then(() => {
                this.syncActiveDevicePlayback();
                this.render();
              });
            } else {
              console.warn('Next track error:', res);
            }
          });
          return;
        }
        if (act === 'prev') {
          BrokerApi.sendPlayerControl('prev').then(res => {
            if (res && res.ok) {
              if (res.data?.track) {
                state.setChapter(Math.max(0, res.data.track - 1));
              } else if (state.chapterIndex > 0) {
                state.setChapter(state.chapterIndex - 1);
              }
              BrokerApi.getDeviceConfig().then(() => {
                this.syncActiveDevicePlayback();
                this.render();
              });
            } else {
              console.warn('Prev track error:', res);
            }
          });
          return;
        }
        if (act === 'vol-down') {
          const maxLimit = (state.activeDevice && state.activeDevice.volume_max != null) ? state.activeDevice.volume_max : 100;
          const cur = state.volume != null ? state.volume : (state.activeDevice?.volume != null ? state.activeDevice.volume : 50);
          const newVol = Math.max(0, Math.min(maxLimit, cur - 10));
          state.volume = newVol;
          if (state.activeDevice) state.activeDevice.volume = newVol;
          this.render();
          BrokerApi.sendPlayerControl('volume', { volume: newVol });
          return;
        }
        if (act === 'vol-up') {
          const maxLimit = (state.activeDevice && state.activeDevice.volume_max != null) ? state.activeDevice.volume_max : 100;
          const cur = state.volume != null ? state.volume : (state.activeDevice?.volume != null ? state.activeDevice.volume : 50);
          const newVol = Math.min(maxLimit, cur + 10);
          state.volume = newVol;
          if (state.activeDevice) state.activeDevice.volume = newVol;
          this.render();
          BrokerApi.sendPlayerControl('volume', { volume: newVol });
          return;
        }
        if (act === 'vol-set') {
          const maxLimit = (state.activeDevice && state.activeDevice.volume_max != null) ? state.activeDevice.volume_max : 100;
          const rect = actBtn.getBoundingClientRect();
          const clickX = e.clientX - rect.left;
          const ratio = Math.max(0, Math.min(1, clickX / rect.width));
          const rawVol = Math.round(ratio * 100);
          const newVol = Math.min(maxLimit, rawVol);
          state.volume = newVol;
          if (state.activeDevice) state.activeDevice.volume = newVol;
          this.render();
          BrokerApi.sendPlayerControl('volume', { volume: newVol });
          return;
        }
        if (act === 'gear-button') {
          e.preventDefault();
          e.stopPropagation();
          state.previousScreen = state.screen;
          state.currentEnteredPin = '';
          state.isPinError = false;
          if (!state.parentPin) {
            state.pinMode = 'setup';
          } else {
            state.pinMode = 'unlock';
          }
          state.setScreen('pin');
          this.render();
          return;
        }
      }
    });
  },

  bindGrownUpsEvents() {
    // Parent volume ceiling slider removed - volume limits are dynamically queried per-device from Yoto
    const bedtimeInput = document.getElementById('guBedtimeInput');
    if (bedtimeInput) {
      bedtimeInput.addEventListener('change', (e) => {
        state.parentSettings.bedtime = e.target.value;
        state.persistParentSettings();
      });
    }
    const wakeInput = document.getElementById('guWakeInput');
    if (wakeInput) {
      wakeInput.addEventListener('change', (e) => {
        state.parentSettings.wakeTime = e.target.value;
        state.persistParentSettings();
      });
    }
    const brightnessSlider = document.getElementById('guBrightnessSlider');
    const brightnessLabel = document.getElementById('guBrightnessLabel');
    if (brightnessSlider) {
      brightnessSlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value, 10);
        state.parentSettings.brightness = val;
        if (brightnessLabel) brightnessLabel.textContent = `${val}%`;
      });
      brightnessSlider.addEventListener('change', (e) => {
        state.persistParentSettings();
      });
    }
  }
};
