// Modern serverless chat application with improved UX
// Inspired by Discord, Slack, and WhatsApp design patterns

(() => {
    // ---------- DOM helpers ----------
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
    const el = (tag, attrs = {}, ...children) => {
        const node = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => {
            if (k === 'class') node.className = v;
            else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
            else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
            else if (v !== undefined && v !== null) node.setAttribute(k, v);
        });
        children.flat().forEach(c => node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
        return node;
    };

    // ---------- State ----------
    const state = {
        username: null,
        token: null,
        wsUrl: null,
        ws: null,
        wsBackoffMs: 500,
        wsMaxBackoffMs: 15000,
        connected: false,
        messages: new Map(),
        isTyping: false,
        onlineUsers: new Set(),
    };

    // ---------- Utilities ----------
    const generateAvatarUrl = (username) => {
        const colors = ['#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#10b981', '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899', '#f43f5e'];
        const color = colors[username.charCodeAt(0) % colors.length];
        const initials = username.slice(0, 2).toUpperCase();
        return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="16" fill="${color}"/><text x="16" y="20" text-anchor="middle" fill="white" font-family="Inter, sans-serif" font-size="12" font-weight="600">${initials}</text></svg>`)}`;
    };

    const formatTime = (timestamp) => {
        const date = new Date(timestamp);
        const now = new Date();
        const isToday = date.toDateString() === now.toDateString();
        
        if (isToday) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } else {
            const yesterday = new Date(now);
            yesterday.setDate(yesterday.getDate() - 1);
            const isYesterday = date.toDateString() === yesterday.toDateString();
            
            if (isYesterday) {
                return `Yesterday ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
            } else {
                return date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            }
        }
    };

    // ---------- Styles ----------
    const styles = `
        /* Modern chat application styles */
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: var(--gray-900);
            overflow: hidden;
        }

        .chat-app {
            height: 100vh;
            display: flex;
            flex-direction: column;
            max-width: 100vw;
            margin: 0 auto;
            background: white;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        }

        @media (min-width: 768px) {
            .chat-app {
                max-width: 1200px;
                height: calc(100vh - 2rem);
                margin: 1rem auto;
                border-radius: 12px;
                overflow: hidden;
            }
        }

        /* Header */
        .header {
            background: white;
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--gray-200);
            display: flex;
            justify-content: space-between;
            align-items: center;
            min-height: 72px;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .app-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--primary-500), var(--primary-700));
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }

        .app-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--gray-900);
        }

        .connection-status {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
            color: var(--gray-600);
        }

        .status-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--red-500);
            transition: background-color 0.3s ease;
        }

        .status-indicator.connected {
            background: var(--green-500);
        }

        .user-info {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
            color: var(--gray-600);
        }

        /* Login Section */
        .login-container {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            background: var(--gray-50);
        }

        .login-card {
            background: white;
            padding: 2.5rem;
            border-radius: 16px;
            box-shadow: 0 10px 25px -3px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
        }

        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }

        .login-title {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--gray-900);
            margin-bottom: 0.5rem;
        }

        .login-subtitle {
            color: var(--gray-600);
            font-size: 0.875rem;
        }

        .auth-tabs {
            display: flex;
            background: var(--gray-100);
            border-radius: 8px;
            padding: 4px;
            margin-bottom: 1.5rem;
        }

        .tab-btn {
            flex: 1;
            padding: 0.75rem;
            text-align: center;
            background: none;
            border: none;
            border-radius: 6px;
            font-weight: 500;
            color: var(--gray-600);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .tab-btn.active {
            background: white;
            color: var(--primary-600);
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
        }

        .auth-form {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .form-label {
            font-weight: 500;
            color: var(--gray-700);
            font-size: 0.875rem;
        }

        .form-input {
            padding: 0.875rem 1rem;
            border: 1px solid var(--gray-300);
            border-radius: 8px;
            font-size: 1rem;
            transition: all 0.2s ease;
            background: white;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--primary-500);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }

        .form-button {
            padding: 0.875rem 1rem;
            background: var(--primary-600);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 0.5rem;
        }

        .form-button:hover:not(:disabled) {
            background: var(--primary-700);
            transform: translateY(-1px);
        }

        .form-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        /* Chat Interface */
        .chat-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: var(--gray-50);
            overflow: hidden; /* Prevents message container from overflowing */
        }

        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
            min-height: 0; /* Crucial for flexbox scrolling */
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .message-group {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .message-group.own {
            align-items: flex-end;
        }

        .message-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.25rem;
            padding: 0 0.75rem;
        }

        .message-group.own .message-header {
            flex-direction: row-reverse;
        }

        .message-avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .message-author {
            font-weight: 600;
            color: var(--gray-900);
            font-size: 0.875rem;
        }

        .message-time {
            font-size: 0.75rem;
            color: var(--gray-500);
        }

        .message-bubble {
            max-width: 70%;
            padding: 0.75rem 1rem;
            border-radius: 16px;
            position: relative;
            word-wrap: break-word;
            animation: messageSlideIn 0.3s ease-out;
        }

        .message-group:not(.own) .message-bubble {
            background: white;
            border: 1px solid var(--gray-200);
            border-bottom-left-radius: 4px;
        }

        .message-group.own .message-bubble {
            background: var(--primary-600);
            color: white;
            border-bottom-right-radius: 4px;
        }

        .message-content {
            line-height: 1.4;
            white-space: pre-wrap;
        }

        @keyframes messageSlideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        /* Message Composer */
        .composer-container {
            padding: 1rem 1.5rem;
            background: white;
            border-top: 1px solid var(--gray-200);
        }

        .composer {
            display: flex;
            align-items: flex-end;
            gap: 0.75rem;
            background: var(--gray-50);
            border-radius: 24px;
            padding: 0.5rem;
            border: 1px solid var(--gray-200);
            transition: all 0.2s ease;
        }

        .composer:focus-within {
            border-color: var(--primary-500);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }

        .message-input {
            flex: 1;
            border: none;
            background: none;
            padding: 0.75rem 1rem;
            font-size: 1rem;
            resize: none;
            outline: none;
            min-height: 44px;
            max-height: 120px;
            font-family: inherit;
        }

        .send-button {
            width: 44px;
            height: 44px;
            background: var(--primary-600);
            border: none;
            border-radius: 50%;
            color: white;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
            flex-shrink: 0;
        }

        .send-button:hover:not(:disabled) {
            background: var(--primary-700);
            transform: scale(1.05);
        }

        .send-button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .send-icon {
            width: 20px;
            height: 20px;
        }

        /* Utility classes */
        .hidden {
            display: none !important;
        }

        .fade-in {
            animation: fadeIn 0.3s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        /* Scrollbar styling */
        .messages-container::-webkit-scrollbar {
            width: 6px;
        }

        .messages-container::-webkit-scrollbar-track {
            background: var(--gray-100);
        }

        .messages-container::-webkit-scrollbar-thumb {
            background: var(--gray-300);
            border-radius: 3px;
        }

        .messages-container::-webkit-scrollbar-thumb:hover {
            background: var(--gray-400);
        }

        /* Mobile responsive */
        @media (max-width: 768px) {
            .login-card {
                padding: 1.5rem;
                margin: 1rem;
            }
            
            .header {
                padding: 1rem;
            }
            
            .message-bubble {
                max-width: 85%;
            }
            
            .composer-container {
                padding: 1rem;
            }
        }
    `;

    // ---------- Create Application ----------
    const app = el('div', { class: 'chat-app' });
    
    // Add styles
    const styleEl = el('style', {}, styles);
    document.head.appendChild(styleEl);

    // Header
    const header = el('div', { class: 'header' },
        el('div', { class: 'header-left' },
            el('div', { class: 'app-icon' }, '💬'),
            el('div', { class: 'app-title' }, 'Serverless Chat')
        ),
        el('div', { class: 'connection-status', id: 'connectionStatus' },
            el('div', { class: 'status-indicator', id: 'statusIndicator' }),
            el('span', { id: 'statusText' }, 'Disconnected')
        )
    );

    // Login container
    const loginContainer = el('div', { class: 'login-container', id: 'loginContainer' },
        el('div', { class: 'login-card' },
            el('div', { class: 'login-header' },
                el('h1', { class: 'login-title' }, 'Welcome to Chat'),
                el('p', { class: 'login-subtitle' }, 'Connect with others in real-time')
            ),
            el('div', { class: 'auth-tabs' },
                el('button', { class: 'tab-btn active', id: 'loginTab' }, 'Sign In'),
                el('button', { class: 'tab-btn', id: 'registerTab' }, 'Sign Up')
            ),
            el('form', { class: 'auth-form', id: 'loginForm' },
                el('div', { class: 'form-group' },
                    el('label', { class: 'form-label' }, 'Username'),
                    el('input', { 
                        class: 'form-input', 
                        id: 'loginUsername', 
                        type: 'text',
                        placeholder: 'Enter your username',
                        autocomplete: 'username',
                        required: true
                    })
                ),
                el('div', { class: 'form-group' },
                    el('label', { class: 'form-label' }, 'Password'),
                    el('input', { 
                        class: 'form-input', 
                        id: 'loginPassword', 
                        type: 'password',
                        placeholder: 'Enter your password',
                        autocomplete: 'current-password',
                        required: true
                    })
                ),
                el('button', { class: 'form-button', type: 'submit', id: 'loginBtn' }, 'Sign In')
            ),
            el('form', { class: 'auth-form hidden', id: 'registerForm' },
                el('div', { class: 'form-group' },
                    el('label', { class: 'form-label' }, 'Username'),
                    el('input', { 
                        class: 'form-input', 
                        id: 'registerUsername', 
                        type: 'text',
                        placeholder: 'Choose a username',
                        autocomplete: 'username',
                        required: true
                    })
                ),
                el('div', { class: 'form-group' },
                    el('label', { class: 'form-label' }, 'Password'),
                    el('input', { 
                        class: 'form-input', 
                        id: 'registerPassword', 
                        type: 'password',
                        placeholder: 'Choose a password (min 8 characters)',
                        autocomplete: 'new-password',
                        required: true,
                        minlength: 8
                    })
                ),
                el('button', { class: 'form-button', type: 'submit', id: 'registerBtn' }, 'Create Account')
            )
        )
    );

    // Chat container
    const chatContainer = el('div', { class: 'chat-container hidden', id: 'chatContainer' },
        el('div', { class: 'messages-container', id: 'messagesContainer' }),
        el('div', { class: 'composer-container' },
            el('div', { class: 'composer' },
                el('textarea', { 
                    class: 'message-input', 
                    id: 'messageInput',
                    placeholder: 'Type a message...',
                    rows: 1
                }),
                el('button', { class: 'send-button', id: 'sendBtn', type: 'button' },
                    el('svg', { class: 'send-icon', viewBox: '0 0 24 24', fill: 'currentColor' },
                        el('path', { d: 'M2.01 21L23 12 2.01 3 2 10l15 2-15 2z' })
                    )
                )
            )
        )
    );

    // Build the app
    app.appendChild(header);
    app.appendChild(loginContainer);
    app.appendChild(chatContainer);
    $('#root').appendChild(app);

    // ---------- State Management ----------
    const setConnectionStatus = (connected, text) => {
        const indicator = $('#statusIndicator');
        const statusText = $('#statusText');
        
        if (connected) {
            indicator.classList.add('connected');
            statusText.textContent = text || 'Connected';
        } else {
            indicator.classList.remove('connected');
            statusText.textContent = text || 'Disconnected';
        }
    };

    const showLoginForm = () => {
        $('#loginContainer').classList.remove('hidden');
        $('#chatContainer').classList.add('hidden');
    };

    const showChatInterface = () => {
        $('#loginContainer').classList.add('hidden');
        $('#chatContainer').classList.remove('hidden');
        $('#chatContainer').classList.add('fade-in');
        setTimeout(() => $('#messageInput').focus(), 100);
    };

    const switchTab = (tab) => {
        const loginTab = $('#loginTab');
        const registerTab = $('#registerTab');
        const loginForm = $('#loginForm');
        const registerForm = $('#registerForm');

        if (tab === 'login') {
            loginTab.classList.add('active');
            registerTab.classList.remove('active');
            loginForm.classList.remove('hidden');
            registerForm.classList.add('hidden');
        } else {
            registerTab.classList.add('active');
            loginTab.classList.remove('active');
            registerForm.classList.remove('hidden');
            loginForm.classList.add('hidden');
        }
    };

    // ---------- Message Handling ----------
    const normalizeMessage = (raw) => {
        const m = raw?.payload?.message ?? raw?.data?.message ?? raw?.message ?? raw?.payload ?? raw?.data ?? raw;
        if (!m || (typeof m !== 'object' && typeof m !== 'string')) {
            if (typeof raw === 'string') return { id: undefined, userName: 'unknown', message: raw, timestamp: Date.now() };
            return null;
        }
        const obj = typeof m === 'string' ? { message: m } : m;
        
        return {
            id: obj.id ?? obj.messageId ?? obj.pk ?? obj.sk ?? `${obj.senderId || obj.userName || obj.username || 'user'}-${obj.createdAt || obj.timestamp || Date.now()}-${Math.random().toString(36).slice(2)}`,
            userName: obj.senderId ?? obj.userName ?? obj.username ?? obj.user ?? obj.author ?? 'unknown',
            message: obj.content ?? obj.message ?? obj.text ?? obj.body ?? '',
            timestamp: obj.createdAt ? new Date(obj.createdAt).getTime() : (obj.timestamp ?? Date.now()),
        };
    };

    const renderMessage = (msg) => {
        if (!msg || state.messages.has(msg.id)) return;
        
        state.messages.set(msg.id, msg);
        const container = $('#messagesContainer');
        const isOwn = state.username && msg.userName && state.username.toLowerCase() === msg.userName.toLowerCase();

        const messageGroup = el('div', { class: `message-group ${isOwn ? 'own' : ''}`, 'data-id': msg.id },
            el('div', { class: 'message-header' },
                el('img', { 
                    class: 'message-avatar', 
                    src: generateAvatarUrl(msg.userName), 
                    alt: `${msg.userName} avatar` 
                }),
                el('span', { class: 'message-author' }, msg.userName),
                el('span', { class: 'message-time' }, formatTime(msg.timestamp))
            ),
            el('div', { class: 'message-bubble' },
                el('div', { class: 'message-content' }, msg.message)
            )
        );

        container.appendChild(messageGroup);
        container.scrollTop = container.scrollHeight;
    };

    const renderInitialMessages = (messages) => {
        if (!Array.isArray(messages)) return;
        
        messages
            .map(normalizeMessage)
            .filter(Boolean)
            .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
            .forEach(renderMessage);
    };

    // ---------- API Configuration ----------
    const API_BASE_URL = (window.CHAT_CONFIG && window.CHAT_CONFIG.API_BASE_URL) 
        ? window.CHAT_CONFIG.API_BASE_URL 
        : 'https://lzypp0ol5j.execute-api.us-east-1.amazonaws.com';

    // ---------- API Functions ----------
    const postJSON = async (path, body, token) => {
        const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(body || {}),
        });
        
        if (!res.ok) {
            const txt = await res.text().catch(() => '');
            throw new Error(`HTTP ${res.status} ${res.statusText} ${txt}`);
        }
        
        try { 
            return await res.json(); 
        } catch { 
            return {}; 
        }
    };

    // ---------- WebSocket Management ----------
    const connectWebSocket = () => {
        if (!state.wsUrl || !state.token) {
            console.warn('Missing wsUrl or token for WebSocket.');
            setConnectionStatus(false, 'Missing WebSocket URL');
            return;
        }

        const url = new URL(state.wsUrl);
        url.searchParams.set('token', state.token);
        url.searchParams.set('username', state.username);

        try {
            state.ws = new WebSocket(url.toString());
        } catch (e) {
            console.error('WebSocket init error:', e);
            setTimeout(connectWebSocket, Math.min(state.wsBackoffMs *= 2, state.wsMaxBackoffMs));
            return;
        }

        state.ws.addEventListener('open', () => {
            state.connected = true;
            state.wsBackoffMs = 500;
            setConnectionStatus(true, 'Connected');
        });

        state.ws.addEventListener('message', (ev) => {
            let data = ev.data;
            try { data = JSON.parse(ev.data); } catch { /* keep as string */ }
            
            if (Array.isArray(data?.messages)) {
                data.messages.map(normalizeMessage).filter(Boolean).forEach(renderMessage);
            } else {
                const msg = normalizeMessage(data);
                if (msg) renderMessage(msg);
            }
        });

        state.ws.addEventListener('close', () => {
            state.connected = false;
            setConnectionStatus(false, 'Reconnecting...');
            state.ws = null;
            setTimeout(connectWebSocket, Math.min(state.wsBackoffMs *= 2, state.wsMaxBackoffMs));
        });

        state.ws.addEventListener('error', (e) => {
            console.error('WebSocket error:', e);
        });
    };

    // ---------- Authentication ----------
    const handleRegister = async (e) => {
        e.preventDefault();
        const username = $('#registerUsername').value.trim();
        const password = $('#registerPassword').value;
        const btn = $('#registerBtn');

        if (!username || !password) {
            alert('Please fill in all fields');
            return;
        }

        if (password.length < 8) {
            alert('Password must be at least 8 characters long');
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Creating account...';
        setConnectionStatus(false, 'Creating account...');

        try {
            const res = await postJSON('/register', { username, password });

            if (res.message || res.username) {
                alert('Account created successfully! Please sign in.');
                switchTab('login');
                $('#loginUsername').value = username;
                $('#registerUsername').value = '';
                $('#registerPassword').value = '';
            } else {
                throw new Error(res.error || 'Registration failed');
            }
        } catch (err) {
            console.error(err);
            alert(`Registration failed: ${err.message}`);
            setConnectionStatus(false, 'Registration failed');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Create Account';
        }
    };

    const handleLogin = async (e) => {
        e.preventDefault();
        const username = $('#loginUsername').value.trim();
        const password = $('#loginPassword').value;
        const btn = $('#loginBtn');

        if (!username || !password) {
            alert('Please enter username and password');
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Signing in...';
        setConnectionStatus(false, 'Signing in...');

        try {
            const res = await postJSON('/login', { username, password });

            if (res.token) {
                state.username = username;
                state.token = res.token;
                state.wsUrl = res.wsUrl || res.websocketUrl || null;

                showChatInterface();
                setConnectionStatus(false, 'Loading messages...');

                // Load historical messages
                try {
                    const messagesRes = await fetch(`${API_BASE_URL}/getStoredMessages?token=${encodeURIComponent(state.token)}`, {
                        method: 'GET',
                        headers: { 'Content-Type': 'application/json' }
                    });
                    
                    if (messagesRes.ok) {
                        const data = await messagesRes.json();
                        renderInitialMessages(data.messages || []);
                    }
                } catch (msgErr) {
                    console.warn('Failed to load message history:', msgErr);
                }

                // Connect to WebSocket
                setConnectionStatus(false, 'Connecting...');
                connectWebSocket();
            } else {
                throw new Error(res.error || 'No token received');
            }
        } catch (err) {
            console.error(err);
            alert(`Login failed: ${err.message}`);
            setConnectionStatus(false, 'Login failed');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Sign In';
        }
    };

    // ---------- Message Sending ----------
    const sendMessage = async () => {
        const input = $('#messageInput');
        const text = input.value.trim();
        if (!text || !state.token) return;

        const btn = $('#sendBtn');
        btn.disabled = true;

        try {
            await postJSON('/addMessages', {
                senderId: state.username,
                content: text,
            }, state.token);
            
            input.value = '';
            input.style.height = 'auto';
        } catch (err) {
            console.error(err);
            alert('Failed to send message. Please try again.');
        } finally {
            btn.disabled = false;
            input.focus();
        }
    };

    // ---------- Event Listeners ----------
    
    // Tab switching
    $('#loginTab').addEventListener('click', () => switchTab('login'));
    $('#registerTab').addEventListener('click', () => switchTab('register'));

    // Form submissions
    $('#loginForm').addEventListener('submit', handleLogin);
    $('#registerForm').addEventListener('submit', handleRegister);

    // Message sending
    $('#sendBtn').addEventListener('click', sendMessage);
    
    // Auto-resize textarea and handle Enter key
    $('#messageInput').addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    $('#messageInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Initialize
    setConnectionStatus(false, 'Disconnected');
    console.log('Modern Serverless Chat initialized');
})();
