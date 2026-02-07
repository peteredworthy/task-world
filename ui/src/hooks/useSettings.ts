import { useState } from 'react';

const STORAGE_KEY = 'orchestrator-settings';

export interface Settings {
  activityStreamMode: 'sse' | 'polling';
}

const DEFAULT_SETTINGS: Settings = {
  activityStreamMode: 'polling',
};

function loadSettings(): Settings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch (error) {
    console.error('Failed to load settings from localStorage:', error);
  }
  return DEFAULT_SETTINGS;
}

function saveSettings(settings: Settings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error('Failed to save settings to localStorage:', error);
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(loadSettings);

  const updateSettings = (updates: Partial<Settings>) => {
    setSettings((prev) => {
      const newSettings = { ...prev, ...updates };
      saveSettings(newSettings);
      return newSettings;
    });
  };

  return { settings, updateSettings };
}
