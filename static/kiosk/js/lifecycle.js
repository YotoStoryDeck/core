import { CONFIG, Utils } from './config.js';
import { state } from './state.js';
import { BrokerApi } from './broker-api.js';

export const lifecycleMixin = {
  async bootstrap() {
    try {
      // 1. Device Registration Handshake
      const regResult = await BrokerApi.registerDevice();
      if (regResult.status === 'pending_approval') {
        this.statusBadge.textContent = 'Device Quarantined (Pending Approval)';
        this.statusBadge.className = 'broker-badge connecting';
        this.container.innerHTML = `
          <div class="profile-screen" style="text-align:center; padding:40px;">
            <div style="font-size:48px; margin-bottom:16px;">⏳</div>
            <div class="profile-title">DEVICE PENDING APPROVAL</div>
            <div class="profile-subtitle" style="margin-top:12px; max-width:480px; line-height:1.5;">
              Device <code>${Utils.esc(CONFIG.DEVICE_ID)}</code> has announced itself to the broker.<br>
              Please approve this device in the Broker Web Admin under <b>Hardware</b> to enable access tokens.<br><br>
              <i>Checking approval status every 5 seconds...</i>
            </div>
          </div>
        `;
        setTimeout(() => this.bootstrap(), 5000);
        return;
      }
      // 2. Discover Hardware Config & Dynamic Profiles
      const conf = await BrokerApi.getDeviceConfig();
      this.statusBadge.textContent = `Connected to Broker (${state.profiles.length} Profiles)`;
      this.statusBadge.className = 'broker-badge';
      // 3. Launch Initial Screen
      if (state.mode === 'standalone') {
        const allPlayers = state.getAllAvailablePlayers();
        if (allPlayers.length > 0) {
          state.setActiveDevice(state.resolveActiveDevice(null));
        }
        if (state.profiles.length > 0) {
          await BrokerApi.fetchLiveCatalog(state.profiles[0].id);
          this.syncActiveDevicePlayback();
        }
        state.setScreen('catalog');
        this.render();
      } else if (conf.assigned_profile && state.profiles.some(p => p.id === conf.assigned_profile)) {
        await this.selectProfile(conf.assigned_profile);
      } else {
        state.setScreen('profile');
        this.render();
      }
      // 4. Start active health & ping monitor with recovery
      this.startHealthMonitor();
    } catch (err) {
      console.warn('Broker communication error:', err);
      this.enterOfflineState();
    }
  },
  /**
   * Transitions UI into offline overlay and remembers prior screen for instant recovery
   */
  /**
   * Transitions UI into Quarantine / Pairing screen when unapproved by admin
   */
  enterQuarantineState() {
    if (state.screen === 'quarantine') return;
    state.setScreen('quarantine');
    state.isPlaying = false;
    state.isApproved = false;
    this.statusBadge.textContent = 'Device Quarantined (Pending Approval)';
    this.statusBadge.className = 'broker-badge connecting';
    this.container.innerHTML = `
      <div class="profile-screen" style="text-align:center; padding:40px;">
        <div style="font-size:48px; margin-bottom:16px;">⏳</div>
        <div class="profile-title">DEVICE PENDING APPROVAL</div>
        <div class="profile-subtitle" style="margin-top:12px; max-width:480px; line-height:1.5;">
          This controller (<code>${Utils.esc(CONFIG.DEVICE_ID)}</code>) is in quarantine.<br>
          Please approve this device in StoryDeck Web Admin under <b>Hardware</b>.<br><br>
          <i>Checking approval status every 5 seconds...</i>
        </div>
      </div>
    `;
    if (!this._quarantineTimer) {
      this._quarantineTimer = setInterval(async () => {
        try {
          const regResult = await BrokerApi.registerDevice();
          if (regResult && regResult.status !== 'pending_approval') {
            clearInterval(this._quarantineTimer);
            this._quarantineTimer = null;
            state.isApproved = true;
            await this.bootstrap();
          }
        } catch (e) {}
      }, 5000);
    }
  },

  enterOfflineState() {
    if (!state.isOffline) {
      state.isOffline = true;
      if (state.screen !== 'offline') {
        state.previousScreen = state.screen;
      }
      state.setScreen('offline');
      this.statusBadge.textContent = 'Broker Offline (Pinging...)';
      this.statusBadge.className = 'broker-badge error';
      this.render();
    }
    // Ping broker every 3 seconds to test for recovery
    if (!this._pingTimer) {
      this._pingTimer = setInterval(async () => {
        const ok = await BrokerApi.ping();
        if (ok) {
          clearInterval(this._pingTimer);
          this._pingTimer = null;
          await this.recoverFromOffline();
        }
      }, 3000);
    }
  },
  /**
   * Recovers from offline state, refreshes config/catalog, and restores previous screen
   */
  async recoverFromOffline() {
    console.log('Broker ping restored! Recovering controller state...');
    state.isOffline = false;
    this.statusBadge.textContent = 'Reconnecting...';
    this.statusBadge.className = 'broker-badge connecting';
    try {
      // Re-register if needed
      await BrokerApi.registerDevice();
      const conf = await BrokerApi.getDeviceConfig();
      if (state.activeProfile) {
        await BrokerApi.fetchLiveCatalog(state.activeProfile.id);
        this.syncActiveDevicePlayback();
      }
      this.statusBadge.textContent = `Connected to Broker (${state.profiles.length} Profiles)`;
      this.statusBadge.className = 'broker-badge';
      // Restore user's previous screen
      const returnTo = state.previousScreen || (state.activeProfile ? 'catalog' : 'profile');
      state.previousScreen = null;
      state.setScreen(returnTo);
      this.render();
      console.log(`Controller successfully restored to screen: ${returnTo}`);
    } catch (e) {
      console.warn('Error during recovery, re-entering offline wait:', e);
      this.enterOfflineState();
    }
  }
};
