// main.js — PoultryConnect global scripts
// Add global JS behavior here (animations, sidebar toggle, etc.)

document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss flash alerts after 5 seconds
    document.querySelectorAll('.alert, .dash-flash, .flash-item').forEach(el => {
        setTimeout(() => {
            el.style.transition = 'opacity 0.4s';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 400);
        }, 5000);
    });
});
