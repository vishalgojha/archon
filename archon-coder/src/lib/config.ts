export interface Config {
    backend: 'localhost' | 'hetzner';
    hetznerUrl: string;
    hetznerApiKey: string;
    ollamaModel: string;
}

const DEFAULT_CONFIG: Config = {
    backend: 'localhost',
    hetznerUrl: '',
    hetznerApiKey: '',
    ollamaModel: 'qwen2.5:3b',
};

let config: Config = { ...DEFAULT_CONFIG };

const STORAGE_KEY = 'archon-config';

export function loadConfig(): Config {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            config = { ...DEFAULT_CONFIG, ...JSON.parse(stored) };
        }
    } catch {}
    return config;
}

export function saveConfig(newConfig: Partial<Config>): Config {
    config = { ...config, ...newConfig };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    return config;
}

export function getConfig(): Config {
    return config;
}

export function getApiBaseUrl(): string {
    if (config.backend === 'hetzner' && config.hetznerUrl) {
        return config.hetznerUrl;
    }
    return 'http://localhost:18765';
}
