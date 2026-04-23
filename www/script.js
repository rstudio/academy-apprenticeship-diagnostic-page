$(document).on('shiny:connected', function (event) {
    checkWebSocketConnectivity();
    checkConnectivity();
});

function copyDiagnosticResults() {
    const items = document.querySelectorAll('.status-item');
    const lines = [];

    items.forEach(item => {
        const icon = item.querySelector('.status-icon');
        const text = item.querySelector('.status-text');
        const value = item.querySelector('.status-value');

        if (text) {
            const label = text.innerText.trim();
            const statusText = icon ? icon.innerText.trim() : '';
            const valueText = value ? value.innerText.trim() : '';
            const parts = [label];
            if (statusText) parts.push(statusText);
            if (valueText) parts.push(valueText);
            lines.push(parts.join(' | '));
        }
    });

    const result = lines.join('\n');
    navigator.clipboard.writeText(result).then(() => {
        const btn = document.getElementById('copy-results-btn');
        if (btn) {
            const original = btn.innerText;
            btn.innerText = 'Copied!';
            btn.classList.add('copy-btn-success');
            setTimeout(() => {
                btn.innerText = original;
                btn.classList.remove('copy-btn-success');
            }, 2000);
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

function checkWebSocketConnectivity() {
    Shiny.setInputValue('websocket_status', 'checking');

    try {
        const ws = new WebSocket(CONFIG.websocketEchoServer);

        const timeout = setTimeout(() => {
            ws.close();
            Shiny.setInputValue('websocket_status', 'error');
            console.error('WebSocket connection timed out');
        }, 5000);

        ws.onopen = () => {
            clearTimeout(timeout);
            ws.close();
            Shiny.setInputValue('websocket_status', 'success');
            console.log('WebSocket connection successful');
        };

        ws.onerror = (error) => {
            clearTimeout(timeout);
            Shiny.setInputValue('websocket_status', 'error');
            console.error('WebSocket connection error:', error);
        };

    } catch (error) {
        Shiny.setInputValue('websocket_status', 'error');
        console.error('WebSocket exception:', error);
    }
}

async function checkConnectivity() {
    for (const check of CONFIG.checks) {
        const inputId = check.id + '_status';
        try {
            await fetch(check.url, {
                mode: 'no-cors',
                cache: 'no-store'
            });
            Shiny.setInputValue(inputId, 'success');
        } catch (error) {
            console.error(check.id + ' check failed:', error);
            Shiny.setInputValue(inputId, 'error');
        }
    }
}
