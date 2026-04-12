import App from './App.svelte';
import './app.css';

const target = document.getElementById('app-root')!;
target.innerHTML = '';

try {
    new App({
        target,
    });
    console.log('Svelte app mounted successfully');
} catch (e: any) {
    console.error('Svelte mount error:', e);
    target.innerHTML = '<div style="color: red; padding: 20px;">ERROR: ' + e.message + '</div>';
}
