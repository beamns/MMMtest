/**
 * Money Making Moves - Complete Dashboard
 */

function mmmDashboard() {
    return {
        // Auth state
        authenticated: false,
        selectedSignal: null,
        marketPulse: null,
        authLoading: false,
        showLoginPassword: false,
        showSignupPassword: false,
        user: null,
        showAuthModal: false,
        authMode: 'login', // 'login' or 'signup'
        
        // Subscription tier
        isPro: false,
        isRookie: false,
        subscriptionTier: 'free',
        freeTickerClicks: parseInt(localStorage.getItem('freeTickerClicks') || '0'),
        
        // Company profile
        companyProfile: null,
        companyProfileLoading: false,
        
        // Watchlist
        watchlist: [],
        showWatchlistPanel: false,
        watchlistAlerts: [],  // tickers that appeared in last scan
        
        // Presets
        presets: [],
        showPresetSave: false,
        newPresetName: '',
        
        // Hot stocks
        hotStocks: [],
        
        // Hot themes
        hotThemes: [],
            hotThemeKeywords: [],
        
        // Activity feed
        activityFeed: [],
        activeUsers: 0,
        
        // Auto-refresh
        autoRefreshEnabled: false,
        autoRefreshInterval: null,
        nextRefreshIn: 60,
        lastScanTime: null,
        
        // UI state
        showSettings: false,
        showTickerModal: false,
        activeTab: 'chart',
        showAccountMenu: false,
        
        selectedTicker: '',
        tickerQuote: null,
        tickerQuoteLoading: false,
        selectedScore: 0,
        selectedAIType: '',
        selectedAnalysis: '',
        selectedTradeLevels: {},
        newsArticles: [],
        isInWatchlist: false,
        
        signals: {
            morning_gaps: [],
            scan_time: null
        },
        settings: {
            min_change_pct: 10.0,
            min_price: 1.0,
            direction: 'both',
            min_ai_score: 0,
            require_ticker_news: false,
            require_hot_theme: false,
            include_after_hours: false
        },
        
        sortColumn: 'price_change_pct',
        sortDirection: 'desc',
        
        marketStatus: {
            is_open: false
        },
        
        isScanning: false,
        scanStats: {},
        lastScanTime: null,
        
        // News Catalysts tab
        activeMainTab: 'movers',
        catalystEntries: [],
        catalystLoading: false,
        catalystAsOf: null,
        catalystSortCol: 'price_change_pct',
        catalystSortDir: 'desc',

        showToast: false,
        toastMessage: '',
        activityNews: [],

        get mergedFeed() {
            const activities = (this.activityFeed || []).map((a, i) => ({ type: 'activity', key: 'a' + i, data: a }));
            const news = (this.activityNews || []).slice(0, 8).map((e, i) => ({ type: 'news', key: 'n' + i, data: e }));
            const pattern = [2, 1, 3, 2, 1, 2, 3, 1];
            const mixed = [];
            let ai = 0, ni = 0, pi = 0;
            while (ai < activities.length || ni < news.length) {
                const take = pattern[pi % pattern.length];
                for (let i = 0; i < take && ai < activities.length; i++) mixed.push(activities[ai++]);
                if (ni < news.length) mixed.push(news[ni++]);
                pi++;
            }
            return mixed.slice(0, 15);
        },

        getMostRecentCloseET() {
            try {
                const nowET = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
                const nowMins = nowET.getHours() * 60 + nowET.getMinutes();
                const closeToday = new Date(nowET);
                closeToday.setHours(16, 0, 0, 0);
                if (nowMins >= 960) return closeToday;
                const closeYesterday = new Date(closeToday);
                closeYesterday.setDate(closeYesterday.getDate() - 1);
                return closeYesterday;
            } catch { return null; }
        },

        isAfterMostRecentClose(catalystAt) {
            if (!catalystAt) return false;
            try {
                const closeET = this.getMostRecentCloseET();
                if (!closeET) return false;
                const catalystET = new Date(new Date(catalystAt).toLocaleString('en-US', { timeZone: 'America/New_York' }));
                return catalystET >= closeET;
            } catch { return false; }
        },

        get sortedCatalysts() {
            if (!this.catalystEntries || this.catalystEntries.length === 0) return [];
            let entries = [...this.catalystEntries];

            if (this.settings.include_after_hours) {
                entries = entries.filter(e => this.isAfterMostRecentClose(e.catalyst_at));
            }
            if (this.settings.direction === 'gainers') entries = entries.filter(e => (e.price_change_pct || 0) > 0);
            else if (this.settings.direction === 'losers') entries = entries.filter(e => (e.price_change_pct || 0) < 0);
            if (this.settings.min_price > 0) entries = entries.filter(e => (e.current_price || 0) >= this.settings.min_price);
            if (this.settings.min_change_pct > 0) entries = entries.filter(e => Math.abs(e.price_change_pct || 0) >= this.settings.min_change_pct);
            if (this.settings.min_ai_score > 0) entries = entries.filter(e => (e.ai_score || 0) >= this.settings.min_ai_score);
            if (this.settings.require_ticker_news) entries = entries.filter(e => e.scanner_qualified || e.tier === 1);
            if (this.settings.require_hot_theme && this.hotThemeKeywords.length > 0) {
                entries = entries.filter(e => {
                    const h = (e.headline || '').toLowerCase();
                    const t = (e.ai_type || '').toLowerCase();
                    return t === 'hot theme' || this.hotThemeKeywords.some(kw => h.includes(kw));
                });
            }
            const col = this.catalystSortCol, dir = this.catalystSortDir;
            return entries.sort((a, b) => {
                let aVal = parseFloat(a[col]), bVal = parseFloat(b[col]);
                if (isNaN(aVal) && isNaN(bVal)) return 0;
                if (isNaN(aVal)) return 1;
                if (isNaN(bVal)) return -1;
                return dir === 'asc' ? aVal - bVal : bVal - aVal;
            });
        },

        get sortedSignals() {
            if (!this.signals.morning_gaps || this.signals.morning_gaps.length === 0) {
                return [];
            }

            const column = this.sortColumn;
            const direction = this.sortDirection;

            let gaps = [...this.signals.morning_gaps];

            // Direction filter
            if (this.settings.direction === 'gainers') gaps = gaps.filter(s => (s.price_change_pct || 0) > 0);
            else if (this.settings.direction === 'losers') gaps = gaps.filter(s => (s.price_change_pct || 0) < 0);

            // Min price
            if (this.settings.min_price > 0) gaps = gaps.filter(s => (s.price || 0) >= this.settings.min_price);

            // Min change %
            if (this.settings.min_change_pct > 0) gaps = gaps.filter(s => Math.abs(s.price_change_pct || 0) >= this.settings.min_change_pct);

            // Min AI score
            if (this.settings.min_ai_score > 0) gaps = gaps.filter(s => (s.ai_score || 0) >= this.settings.min_ai_score);

            // Ticker news: only show stocks where the ticker is explicitly mentioned in the news
            if (this.settings.require_ticker_news) gaps = gaps.filter(s => s.has_exact_mention || s.has_news);

            // Hot theme filter
            if (this.settings.require_hot_theme) {
                if (this.hotThemeKeywords.length > 0) {
                    gaps = gaps.filter(s => {
                        const catalyst = (s.catalyst || '').toLowerCase();
                        const epType = (s.ep_type || '').toLowerCase();
                        return epType === 'hot theme' || this.hotThemeKeywords.some(kw => catalyst.includes(kw));
                    });
                }
            }

            return gaps.sort((a, b) => {
                let aVal = parseFloat(a[column]);
                let bVal = parseFloat(b[column]);
                if (isNaN(aVal) && isNaN(bVal)) return 0;
                if (isNaN(aVal)) return 1;
                if (isNaN(bVal)) return -1;
                if (direction === 'asc') return aVal - bVal;
                return bVal - aVal;
            });
        },
        
        init() {
            setTimeout(() => this.checkAuth(), 300);
            this.loadMarketStatus();
            this.loadMarketPulse();
            this.loadSettings();
            this.loadHotStocks();
            this.loadHotThemes();
            this.loadActivityFeed();
            this.loadActivityNews();
            this.loadNewsCatalysts();
            this.loadPresets();

            setInterval(() => {
                this.loadActivityFeed();
                this.loadActivityNews();
            }, 10000);

            // Auto-run scan on first visit (if no results yet)
            setTimeout(() => {
                if (this.signals.morning_gaps.length === 0) {
                    this.runScan();
                }
            }, 1000); // Wait 1 second for page to load
            
            // Handle browser back button to close modal
            window.addEventListener('popstate', (e) => {
                if (this.showTickerModal) {
                    this.showTickerModal = false;
                }
            });
            
            // Handle ticker search
            window.addEventListener('open-ticker', async (e) => {
                const ticker = e.detail.ticker;
                if (!ticker) return;
                // Paywall check
                if (!this.isPro) {
                    this.toast('⭐ Ticker search is a Pro feature — upgrade to unlock', 'error');
                    this.showAuthModal = true;
                    this.authMode = 'upgrade';
                    return;
                }
                // Look for ticker in current signals first
                const existing = this.signals.morning_gaps?.find(s => s.ticker === ticker);
                if (existing) {
                    this.openTickerModal(existing);
                } else {
                    // Open modal immediately with placeholder, then fetch AI analysis
                    this.openTickerModal({
                        ticker,
                        price: 0,
                        ai_score: 0,
                        ai_type: '',
                        ai_reason: 'Fetching analysis...',
                        ai_recommendation: 'Fetching analysis...',
                        direction: 'long',
                        trade_levels: {}
                    });
                    // Fetch live AI analysis in background
                    try {
                        const resp = await fetch(`/api/analyze/${ticker}`);
                        const data = await resp.json();
                        if (data.success) {
                            this.selectedScore = data.ai_score;
                            this.selectedAIType = data.ai_type;
                            this.selectedAnalysis = data.ai_recommendation || data.ai_reason;
                            if (this.selectedSignal) {
                                this.selectedSignal.direction = data.direction;
                                this.selectedSignal.price = data.price;
                                this.selectedSignal.gap_pct = data.pct_change;
                            }
                        }
                    } catch(e) {
                    }
                }
            });

            setInterval(() => {
                this.loadMarketStatus();
            }, 30000);
            

        },
        
        // Auth methods
        async checkAuth() {
            const token = localStorage.getItem('mmm_token');
            
            if (!token) {
                this.authenticated = false;
                return;
            }
            
            try {
                const response = await fetch('/api/auth/me', {
                    headers: {'Authorization': 'Bearer ' + token}
                });
                
                if (!response.ok) {
                    // Token invalid/expired - clear it
                        localStorage.removeItem('mmm_token');
                    this.authenticated = false;
                    return;
                }
                
                const data = await response.json();
                
                if (data.authenticated) {
                    this.authenticated = true;
                    this.user = data.user;
                    this.isPro = data.user?.is_subscribed && data.user?.subscription_tier === 'pro';
                    this.isRookie = data.user?.is_subscribed && data.user?.subscription_tier === 'rookie';
                    this.subscriptionTier = data.user?.subscription_tier || 'free';
                    await this.loadWatchlist();
                } else {
                    localStorage.removeItem('mmm_token');
                    this.authenticated = false;
                }
            } catch (error) {
            }
        },
        
        async login(email, password) {
            if (!email || !password) {
                this.toast('⚠️ Email and password are required', 'error');
                return;
            }
            this.authLoading = true;
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('mmm_token') ? {'Authorization': 'Bearer ' + localStorage.getItem('mmm_token')} : {})
                    },
                    body: JSON.stringify({ email, password })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    if (data.token) localStorage.setItem('mmm_token', data.token);
                    this.showAuthModal = false;
                    await this.checkAuth();
                    this.toast('✅ Welcome back!');
                } else {
                    this.toast('❌ ' + (data.error || 'Invalid email or password'), 'error');
                }
            } catch (error) {
                this.toast('❌ Error: ' + error.message, 'error');
            } finally {
                this.authLoading = false;
            }
        },
        
        async signup(email, username, password, passwordConfirm) {
            if (!email || !username || !password) {
                this.toast('⚠️ All fields are required', 'error');
                return;
            }
            if (password.length < 8) {
                this.toast('⚠️ Password must be at least 8 characters', 'error');
                return;
            }
            if (password !== passwordConfirm) {
                this.toast('⚠️ Passwords do not match', 'error');
                return;
            }
            this.authLoading = true;
            try {
                const response = await fetch('/api/auth/signup', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('mmm_token') ? {'Authorization': 'Bearer ' + localStorage.getItem('mmm_token')} : {})
                    },
                    body: JSON.stringify({ email, username, password })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    if (data.token) localStorage.setItem('mmm_token', data.token);
                    this.showAuthModal = false;
                    await this.checkAuth();
                    this.toast('🎉 Account created! Welcome, ' + username + '!');
                } else {
                    this.toast('❌ ' + (data.error || 'Could not create account'), 'error');
                }
            } catch (error) {
                this.toast('❌ Error: ' + error.message, 'error');
            } finally {
                this.authLoading = false;
            }
        },
        
        async logout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
                localStorage.removeItem('mmm_token');
                this.authenticated = false;
                this.isPro = false;
                this.isRookie = false;
                this.subscriptionTier = 'free';
                this.user = null;
                this.watchlist = [];
                this.showAccountMenu = false;
                this.toast('Logged out');
            } catch (error) {
            }
        },
        
        // Watchlist methods
        async loadWatchlist() {
            const token = localStorage.getItem('mmm_token');
            if (!token) return;
            try {
                const response = await fetch('/api/watchlist', {
                    headers: {'Authorization': 'Bearer ' + token}
                });
                const data = await response.json();
                if (response.ok) {
                    this.watchlist = data.watchlist || [];
                }
            } catch (error) {
            }
        },
        
        async toggleWatchlist(ticker) {
            if (!this.authenticated) {
                this.showAuthModal = true;
                this.authMode = 'signup';
                return;
            }
            
            const isInList = this.watchlist.some(w => w.ticker === ticker);
            
            const token = localStorage.getItem('mmm_token');
            const authHeader = token ? {'Authorization': 'Bearer ' + token} : {};
            try {
                if (isInList) {
                    await fetch(`/api/watchlist/${ticker}`, {
                        method: 'DELETE',
                        headers: authHeader
                    });
                    this.watchlist = this.watchlist.filter(w => w.ticker !== ticker);
                    this.toast(`Removed ${ticker} from watchlist`);
                } else {
                    const response = await fetch('/api/watchlist', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', ...authHeader },
                        body: JSON.stringify({ ticker })
                    });
                    const data = await response.json();
                    if (data.success) {
                        this.watchlist.push({ ticker });
                        this.toast(`⭐ Added ${ticker} to watchlist`);
                    }
                }
                this.isInWatchlist = this.watchlist.some(w => w.ticker === this.selectedTicker);
            } catch (error) {
                this.toast('Error updating watchlist', 'error');
            }
        },
        
        isTickerInWatchlist(ticker) {
            return this.watchlist.some(w => w.ticker === ticker);
        },
        
        // Hot stocks
        async loadHotStocks() {
            try {
                const response = await fetch('/api/analytics/hot-stocks');
                const data = await response.json();
                
                if (data.success) {
                    this.hotStocks = data.hot_stocks || [];
                }
            } catch (error) {
            }
        },
        
        async loadHotThemes() {
            try {
                const response = await fetch('/api/themes/hot');
                const data = await response.json();
                
                if (data.success) {
                    this.hotThemes = data.themes || [];
                    // Flatten all keywords from active themes for catalyst matching
                    const kwMap = data.keywords || {};
                    this.hotThemeKeywords = Object.values(kwMap).flat();
                }
            } catch (error) {
            }
        },
        
        async loadActivityFeed() {
            try {
                const response = await fetch('/api/activity/feed');
                const data = await response.json();
                
                if (data.success) {
                    this.activityFeed = data.activities || [];
                    this.activeUsers = data.active_users || 0;
                } else {
                }
            } catch (error) {
            }
        },
        
        async trackActivity(type, ticker = null, aiScore = null, priceChange = null) {
            try {
                await fetch('/api/activity/track', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('mmm_token') ? {'Authorization': 'Bearer ' + localStorage.getItem('mmm_token')} : {})
                    },
                    body: JSON.stringify({
                        type: type,
                        ticker: ticker,
                        ai_score: aiScore,
                        price_change: priceChange
                    })
                });
            } catch (error) {
            }
        },
        
        sortBy(column) {
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                this.sortDirection = 'desc';
            }
        },
        
        async loadMarketStatus() {
            try {
                const response = await fetch('/api/market/status');
                const data = await response.json();
                this.marketStatus = data;

            } catch (error) {
            }
        },

        async loadMarketPulse() {
            try {
                const resp = await fetch('/api/market/pulse');
                const data = await resp.json();
                if (data.success) this.marketPulse = data;
            } catch(e) {}
        },
        
        async runScan() {
            if (this.isScanning) return;
            
            this.isScanning = true;
            
            try {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 90000); // 90s timeout
                
                const response = await fetch('/api/scan', {
                    method: 'POST',
                    signal: controller.signal,
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('mmm_token') ? {'Authorization': 'Bearer ' + localStorage.getItem('mmm_token')} : {})
                    },
                    body: JSON.stringify({
                        min_change_pct: parseFloat(this.settings.min_change_pct),
                        min_price: parseFloat(this.settings.min_price),
                        direction: this.settings.direction,
                        min_ai_score: parseInt(this.settings.min_ai_score),
                        require_ticker_news: Boolean(this.settings.require_ticker_news),
                        include_after_hours: Boolean(this.settings.include_after_hours)
                    })
                });
                clearTimeout(timeout);
                
                const data = await response.json();
                
                if (data.success) {
                    this.signals = data.results;
                    this.scanStats = data.scan_stats || {};
                    this.lastScanTime = new Date(data.results.scan_time);
                    this.isPro = data.is_pro && this.subscriptionTier === 'pro';
                    this.isRookie = data.is_pro && this.subscriptionTier === 'rookie';
                    
                    const withScores = this.signals.morning_gaps.filter(s => s.ai_score >= 80).length;
                    const scoreText = withScores > 0 ? ` (${withScores} with 80+ scores)` : '';
                    
                    this.toast(`💰 Found ${data.total_signals} movers${scoreText}`);
                    
                    // Check watchlist alerts
                    this.checkWatchlistAlerts();
                    
                    // Start auto-refresh after successful scan
                    this.startAutoRefresh();
                } else {
                    this.toast('Scan failed: ' + data.error, 'error');
                }
            } catch (error) {
                if (error.name === 'AbortError') {
                    this.toast('⏱ Scan timed out — server is busy, try again', 'error');
                } else {
                    this.toast('Error: ' + error.message, 'error');
                }
            } finally {
                this.isScanning = false;
            }
        },
        
        startAutoRefresh() {
            if (!this.autoRefreshEnabled) return;
            
            // Clear existing interval
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
            }
            
            // Update every 30 seconds
            this.autoRefreshInterval = setInterval(() => {
                if (!this.autoRefreshEnabled || !this.lastScanTime) {
                    return;
                }
                
                const ageMinutes = (Date.now() - this.lastScanTime) / 60000;
                
                // Smart refresh based on age
                if (ageMinutes < 5) {
                    this.refreshScanResults();
                    this.loadNewsCatalysts();
                } else if (ageMinutes < 30) {
                    if (Math.floor(ageMinutes * 2) % 2 === 0) {
                        this.refreshScanResults();
                        this.loadNewsCatalysts();
                    }
                } else {
                    if (Math.floor(ageMinutes) % 5 === 0) {
                        this.refreshScanResults();
                        this.loadNewsCatalysts();
                    }
                }
            }, 30000); // Check every 30 seconds
        },
        
        async refreshScanResults() {
            if (this.isScanning) return; // Don't refresh while manual scan is running
            
            try {
                const response = await fetch('/api/scan', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('mmm_token') ? {'Authorization': 'Bearer ' + localStorage.getItem('mmm_token')} : {})
                    },
                    body: JSON.stringify(this.settings)
                });
                
                const data = await response.json();
                
                if (data.success) {
                    const oldCount = this.signals.morning_gaps?.length || 0;
                    const newCount = data.total_signals;

                    // Preserve scroll position across re-render
                    const scroller = document.querySelector('.scrollable-table-container');
                    const scrollTop = scroller ? scroller.scrollTop : 0;

                    this.signals = data.results || data;
                    this.lastScanTime = new Date(data.results.scan_time);

                    this.$nextTick(() => { if (scroller) scroller.scrollTop = scrollTop; });

                    // Notify if new stocks appeared
                    if (newCount > oldCount) {
                        const diff = newCount - oldCount;
                        this.toast(`✨ ${diff} new stock${diff > 1 ? 's' : ''} found!`);
                    }
                }
            } catch (error) {
            }
        },
        
        async loadActivityNews() {
            try {
                const resp = await fetch('/api/activity/news');
                const data = await resp.json();
                if (data.entries) this.activityNews = data.entries;
            } catch (e) { }
        },

        async loadNewsCatalysts() {
            this.catalystLoading = true;
            try {
                const resp = await fetch('/api/news-catalysts');
                const data = await resp.json();
                if (data.entries) {
                    // Preserve scroll position across re-render
                    const scroller = document.querySelector('.scrollable-table-container');
                    const scrollTop = scroller ? scroller.scrollTop : 0;

                    this.catalystEntries = data.entries;
                    this.catalystAsOf = data.as_of;

                    this.$nextTick(() => { if (scroller) scroller.scrollTop = scrollTop; });
                }
            } catch (e) {
            } finally {
                this.catalystLoading = false;
            }
        },

        stopAutoRefresh() {
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
                this.autoRefreshInterval = null;
            }
        },
        
        toggleAutoRefresh() {
            this.autoRefreshEnabled = !this.autoRefreshEnabled;
            if (this.autoRefreshEnabled) {
                this.toast('🔄 Auto-refresh enabled');
                this.startAutoRefresh();
            } else {
                this.toast('⏸️ Auto-refresh paused');
                this.stopAutoRefresh();
            }
        },
        
        async loadSettings() {
            try {
                // Load from localStorage
                const saved = localStorage.getItem('scannerSettings');
                if (saved) {
                    const settings = JSON.parse(saved);
                    this.settings.min_change_pct = settings.min_change_pct || 10.0;
                    this.settings.min_price = settings.min_price || 1.0;
                    this.settings.direction = settings.direction || 'both';
                    this.settings.min_ai_score = settings.min_ai_score || 0;
                    this.settings.require_ticker_news = settings.require_ticker_news || false;
                    this.settings.require_hot_theme = settings.require_hot_theme || false;
                    // Never restore after_hours from localStorage — always default off
                    this.settings.include_after_hours = false;
                }
            } catch (error) {
            }
        },
        
        async saveSettings() {
            try {
                // Save to localStorage only
                localStorage.setItem('scannerSettings', JSON.stringify(this.settings));
            } catch (error) {
            }
        },
        
        async loadTickerQuote(ticker) {
            this.tickerQuote = null;
            this.tickerQuoteLoading = true;
            try {
                const resp = await fetch(`/api/quote/${ticker}`);
                const data = await resp.json();
                if (data.success) this.tickerQuote = data;
            } catch (e) {
            } finally {
                this.tickerQuoteLoading = false;
            }
        },

        async openTickerModal(signal) {
            this.selectedTicker = signal.ticker;
            this.loadTickerQuote(signal.ticker);
            this.selectedSignal = signal;
            this.selectedScore = signal.ai_score || 0;
            this.selectedAIType = signal.ai_type || 'N/A';
            this.selectedAnalysis = signal.ai_recommendation || signal.ai_reason || 'No analysis available';
            this.selectedTradeLevels = signal.trade_levels || {};
            
            // Check if in watchlist
            this.isInWatchlist = this.watchlist.some(w => w.ticker === signal.ticker);
            
            this.activeTab = 'chart';
            this.companyProfile = null;
            this.showTickerModal = true;
            
            // Push history state so back button closes modal
            history.pushState({ modalOpen: true, ticker: signal.ticker }, '', '');
            
            // Track activity
            this.trackActivity('view_stock', signal.ticker, signal.ai_score);
            
            setTimeout(() => {
                this.loadTradingViewChart(signal.ticker);
            }, 100);
            
            this.loadCompanyProfile(signal.ticker);
            await this.loadNewsArticles(signal.ticker);
        },
        
        loadTradingViewChart(ticker) {
            const containerId = 'tradingview_' + ticker;
            const container = document.getElementById(containerId);
            if (!container) return;
            container.innerHTML = '';

            const isMobile = window.innerWidth < 640;

            new TradingView.widget({
                "autosize": true,
                "symbol": ticker,
                "interval": "5",
                "timezone": "America/New_York",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#0a0a0f",
                "enable_publishing": false,
                "hide_side_toolbar": isMobile,
                "allow_symbol_change": true,
                "extended_hours": true,
                "hide_top_toolbar": false,
                "save_image": false,
                "container_id": containerId
            });
        },
        
        async loadNewsArticles(ticker) {
            this.newsArticles = [];
            
            try {
                const response = await fetch(`/api/news/${ticker}?limit=15`);
                const data = await response.json();
                
                if (data.success && data.news) {
                    this.newsArticles = data.news;
                }
            } catch (error) {
            }
        },
        
        toast(message, type = 'success') {
            this.toastMessage = message;
            this.showToast = true;
            setTimeout(() => {
                this.showToast = false;
            }, 3000);
        },
        
        formatTime(timestamp) {
            if (!timestamp) return 'Never';
            const date = new Date(timestamp);
            const now = new Date();
            const diff = Math.floor((now - date) / 1000);
            
            if (diff < 60) return 'Just now';
            if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
            if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
            
            return date.toLocaleString('en-US', { 
                month: 'short', 
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        },
        
        formatNewsTime(timestamp) {
            if (!timestamp) return '';
            const date = new Date(timestamp);
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        },

        // ========== WATCHLIST PANEL ==========

        async updateWatchlistItem(ticker, field, value) {
            const token = localStorage.getItem('mmm_token');
            try {
                const body = {};
                body[field] = value;
                await fetch(`/api/watchlist/${ticker}`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(token ? {'Authorization': 'Bearer ' + token} : {})
                    },
                    body: JSON.stringify(body)
                });
                // Update local state
                const item = this.watchlist.find(w => w.ticker === ticker);
                if (item) item[field] = value;
            } catch (e) {
                this.toast('Error updating watchlist', 'error');
            }
        },

        // ========== WATCHLIST ALERTS ==========

        checkWatchlistAlerts() {
            if (!this.watchlist.length || !this.signals.morning_gaps.length) return;
            const watchTickers = this.watchlist.map(w => w.ticker.toUpperCase());
            const hits = this.signals.morning_gaps.filter(s =>
                watchTickers.includes(s.ticker.toUpperCase())
            );
            this.watchlistAlerts = hits;
            if (hits.length > 0) {
                const names = hits.map(h => h.ticker).join(', ');
                this.toast(`🔔 Watchlist alert: ${names} is moving!`, 'alert');
            }
        },

        // ========== PRESETS ==========

        async loadPresets() {
            try {
                const token = localStorage.getItem('mmm_token');
                if (!token) return;
                const response = await fetch('/api/presets', {
                    headers: {'Authorization': 'Bearer ' + token}
                });
                const data = await response.json();
                if (data.success) this.presets = data.presets || [];
            } catch (e) {
            }
        },

        async savePreset() {
            if (!this.newPresetName.trim()) return;
            const token = localStorage.getItem('mmm_token');
            try {
                const response = await fetch('/api/presets', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token
                    },
                    body: JSON.stringify({
                        name: this.newPresetName.trim(),
                        settings: { ...this.settings }
                    })
                });
                const data = await response.json();
                if (data.success) {
                    this.presets.push(data.preset);
                    this.newPresetName = '';
                    this.showPresetSave = false;
                    this.toast(`✅ Preset "${data.preset.name}" saved`);
                } else {
                    this.toast(data.error || 'Failed to save preset', 'error');
                }
            } catch (e) {
                this.toast('Error saving preset', 'error');
            }
        },

        loadPreset(preset) {
            const s = preset.settings;
            this.settings.min_change_pct = s.min_change_pct || 10;
            this.settings.min_price = s.min_price || 1.0;
            this.settings.direction = s.direction || 'both';
            this.settings.min_ai_score = s.min_ai_score || 0;
            this.settings.require_ticker_news = s.require_ticker_news || false;
            this.settings.require_hot_theme = s.require_hot_theme || false;
            this.settings.include_after_hours = s.include_after_hours || false;
            this.saveSettings();
            this.toast(`📋 Loaded preset: ${preset.name}`);
        },

        async deletePreset(presetId) {
            const token = localStorage.getItem('mmm_token');
            try {
                await fetch(`/api/presets/${presetId}`, {
                    method: 'DELETE',
                    headers: {'Authorization': 'Bearer ' + token}
                });
                this.presets = this.presets.filter(p => p.id !== presetId);
                this.toast('Preset deleted');
            } catch (e) {
                this.toast('Error deleting preset', 'error');
            }
        },

        // ========== COMPANY PROFILE ==========

        async loadCompanyProfile(ticker) {
            this.companyProfileLoading = true;
            try {
                const response = await fetch(`/api/company/${ticker}`);
                const data = await response.json();
                if (data.success) {
                    this.companyProfile = data.profile;
                }
            } catch (e) {
            } finally {
                this.companyProfileLoading = false;
            }
        },

        // ========== BILLING ==========

        async createCheckout(tier = 'pro') {
            if (!this.authenticated) {
                this.showAuthModal = true;
                this.authMode = 'login';
                this.toast('Sign in first to upgrade', 'error');
                return;
            }
            const token = localStorage.getItem('mmm_token');
            try {
                this.toast('Opening checkout...');
                const response = await fetch('/api/subscription/checkout', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(token ? {'Authorization': 'Bearer ' + token} : {})
                    },
                    body: JSON.stringify({ tier })
                });
                const data = await response.json();
                if (data.success && data.url) {
                    window.location.href = data.url;
                } else {
                    this.toast(data.error || 'Could not open checkout', 'error');
                }
            } catch (e) {
                this.toast('Error opening checkout', 'error');
            }
        },

        async manageBilling() {
            // Free users go to checkout, pro users go to billing portal
            if (!this.isPro && !this.isRookie) {
                return this.createCheckout();
            }
            const token = localStorage.getItem('mmm_token');
            try {
                this.toast('Opening billing portal...');
                const response = await fetch('/api/subscription/billing-portal', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(token ? {'Authorization': 'Bearer ' + token} : {})
                    }
                });
                const data = await response.json();
                if (data.success && data.url) {
                    window.location.href = data.url;
                } else {
                    this.toast(data.message || data.error || 'Could not open billing portal', 'error');
                }
            } catch (e) {
                this.toast('Error opening billing portal', 'error');
            }
        },

    };
}

document.addEventListener('alpine:init', () => {
});

