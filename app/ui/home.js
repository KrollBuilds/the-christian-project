(function() {
    const doc = window.parent?.document || window.document;
    if (!doc) {
        return;
    }
    const body = doc.body;
    if (!body) {
        return;
    }

    if (window.__tcp_ui_enhancer_initialized) {
        if (typeof window.__tcp_refresh_buttons === "function") {
            window.__tcp_refresh_buttons();
        }
        if (typeof window.__tcp_apply_theme === "function") {
            window.__tcp_apply_theme();
        }
        return;
    }
    window.__tcp_ui_enhancer_initialized = true;

    // Theme management function
    window.__tcp_apply_theme = function() {
        // First, check for theme state from hidden div (most reliable)
        const themeDiv = doc.getElementById('theme-state');
        if (themeDiv) {
            const theme = themeDiv.getAttribute('data-theme');
            if (theme === 'dark') {
                body.setAttribute('data-theme', 'dark');
                return;
            } else if (theme === 'light') {
                body.removeAttribute('data-theme');
                return;
            }
        }

        // Fallback: Check if user has selected a theme via radio button
        const radioButtons = doc.querySelectorAll('input[type="radio"]');
        let userTheme = null;
        radioButtons.forEach((radio) => {
            if (radio.checked) {
                const label = radio.closest('label');
                if (label && label.textContent) {
                    const text = label.textContent.trim();
                    if (text.trim() === 'Dark') {
                        userTheme = 'dark';
                    } else if (text.trim() === 'Light') {
                        userTheme = 'light';
                    }
                }
            }
        });

        if (userTheme === 'dark') {
            body.setAttribute('data-theme', 'dark');
        } else if (userTheme === 'light') {
            body.removeAttribute('data-theme');
        } else {
            // Fall back to system preference if no explicit selection
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            if (mediaQuery.matches) {
                body.setAttribute('data-theme', 'dark');
            } else {
                body.removeAttribute('data-theme');
            }
        }
    };

    // Apply theme on load and when radio buttons change
    window.__tcp_apply_theme();
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', window.__tcp_apply_theme);
    } else if (mediaQuery.addListener) {
        mediaQuery.addListener(window.__tcp_apply_theme);
    }

    const enhanceButtons = () => {
        const hamburgerButtons = Array.from(doc.querySelectorAll('button'))
            .filter((btn) => btn.textContent?.trim() === '☰');
        hamburgerButtons.forEach((btn) => {
            if (btn.dataset.enhanced === 'true') {
                return;
            }
            btn.dataset.enhanced = 'true';
            btn.setAttribute('aria-label', 'Open navigation menu');
            btn.setAttribute('aria-expanded', 'false');
            btn.setAttribute('aria-controls', 'sidebar-panel');
            btn.setAttribute('title', 'Open navigation menu');
            btn.setAttribute('type', 'button');

            // Add keyboard navigation
            btn.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    btn.click();
                }
            });
        });

        const sendButtons = Array.from(doc.querySelectorAll('[data-testid="stChatInput"] button[data-testid="baseButton-secondary"]'));
        sendButtons.forEach((btn) => {
            if (btn.dataset.enhanced === 'true') {
                return;
            }
            btn.dataset.enhanced = 'true';
            btn.setAttribute('aria-label', 'Send message');
            btn.setAttribute('title', 'Send message');
            btn.innerHTML = '';
            const span = doc.createElement('span');
            span.className = 'send-button-label';
            span.textContent = 'Ask';
            btn.appendChild(span);
        });

        // Add ARIA labels to primary buttons like "New Chat"
        const primaryButtons = doc.querySelectorAll('[data-testid="baseButton-primary"]');
        primaryButtons.forEach((btn) => {
            if (!btn.getAttribute('aria-label') && btn.textContent.includes('New Chat')) {
                btn.setAttribute('aria-label', 'Start new conversation');
                btn.setAttribute('title', 'Start new conversation');
            }
        });

        // Make chat messages keyboard focusable
        const messages = doc.querySelectorAll('.stChatMessage');
        messages.forEach((msg, idx) => {
            if (!msg.getAttribute('tabindex')) {
                msg.setAttribute('tabindex', '0');
                msg.setAttribute('role', 'article');
                msg.setAttribute('aria-label', `Message ${idx + 1}`);
            }
        });

        // Add skip to main content link for keyboard users
        if (!doc.getElementById('skip-to-main')) {
            const skipLink = doc.createElement('a');
            skipLink.id = 'skip-to-main';
            skipLink.href = '#main-content';
            skipLink.textContent = 'Skip to main content';
            skipLink.className = 'skip-link';
            skipLink.addEventListener('click', (e) => {
                e.preventDefault();
                const main = doc.querySelector('main') || doc.querySelector('[role="main"]');
                if (main) {
                    main.setAttribute('tabindex', '-1');
                    main.focus();
                }
            });
            body.insertBefore(skipLink, body.firstChild);
        }

        // Mark main content area
        const mainContent = doc.querySelector('main');
        if (mainContent && !mainContent.id) {
            mainContent.id = 'main-content';
            mainContent.setAttribute('role', 'main');
        }
    };

    const observer = new MutationObserver(() => {
        enhanceButtons();
        window.__tcp_apply_theme();
    });
    observer.observe(doc, { childList: true, subtree: true });
    enhanceButtons();
    window.__tcp_refresh_buttons = enhanceButtons;

    // Mobile keyboard handling for iOS and Android
    if ('visualViewport' in window) {
        let keyboardVisible = false;
        let dismissBar = null;

        const blurActiveInput = () => {
            const activeEl = doc.activeElement;
            if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
                activeEl.blur();
            }
        };

        const createDismissBar = () => {
            if (dismissBar) return dismissBar;

            // Create a "Done" bar that appears above the keyboard
            dismissBar = doc.createElement('div');
            dismissBar.id = 'tcp-keyboard-dismiss-bar';
            dismissBar.innerHTML = `
                <button type="button" id="tcp-done-btn">Done</button>
            `;
            dismissBar.style.cssText = `
                position: fixed;
                left: 0;
                right: 0;
                height: 44px;
                background: var(--bg-sidebar, #0f0f10);
                border-top: 1px solid var(--border, rgba(255,255,255,0.07));
                display: none;
                align-items: center;
                justify-content: flex-end;
                padding: 0 1rem;
                z-index: 16;
                box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.3);
            `;

            const doneBtn = dismissBar.querySelector('#tcp-done-btn');
            doneBtn.style.cssText = `
                background: transparent;
                border: none;
                color: var(--accent, #c9a84c);
                font-weight: 600;
                font-size: 1rem;
                padding: 0.5rem 1rem;
                cursor: pointer;
                font-family: var(--font-body, sans-serif);
            `;
            doneBtn.addEventListener('click', blurActiveInput);

            doc.body.appendChild(dismissBar);
            return dismissBar;
        };

        const handleKeyboard = () => {
            const chatInput = doc.querySelector('.chat-input-region [data-testid="stChatInput"]');
            const chatScroll = doc.querySelector('.chat-scroll');
            const mainContainer = doc.querySelector('main .block-container');
            const keyboardHeight = window.innerHeight - window.visualViewport.height;
            const wasKeyboardVisible = keyboardVisible;
            keyboardVisible = keyboardHeight > 100; // Threshold to avoid false positives

            if (chatInput) {
                if (keyboardVisible) {
                    // Keyboard is visible - adjust input position and scroll
                    const inputBottom = keyboardHeight;
                    chatInput.style.bottom = `${inputBottom}px`;

                    // Show dismiss bar just above the input
                    const bar = createDismissBar();
                    bar.style.display = 'flex';
                    bar.style.bottom = `${inputBottom + chatInput.offsetHeight}px`;

                    // Add extra padding to main content so messages aren't hidden
                    if (mainContainer) {
                        mainContainer.style.paddingBottom = `${keyboardHeight + 140}px`;
                    }

                    // Auto-scroll to show latest message
                    if (chatScroll && !wasKeyboardVisible) {
                        setTimeout(() => {
                            chatScroll.scrollTop = chatScroll.scrollHeight;
                        }, 100);
                    }
                } else {
                    // Keyboard is hidden - reset everything
                    chatInput.style.bottom = 'env(safe-area-inset-bottom, 0)';

                    // Hide dismiss bar
                    if (dismissBar) {
                        dismissBar.style.display = 'none';
                    }

                    if (mainContainer) {
                        mainContainer.style.paddingBottom = '';
                    }

                }
            }
        };

        window.visualViewport.addEventListener('resize', handleKeyboard);
        window.visualViewport.addEventListener('scroll', handleKeyboard);

        // Also handle focus events for additional reliability
        doc.addEventListener('focusin', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                setTimeout(handleKeyboard, 300);
            }
        });

        doc.addEventListener('focusout', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                setTimeout(handleKeyboard, 100);
            }
        });

        // Initial check
        handleKeyboard();
    }
})();