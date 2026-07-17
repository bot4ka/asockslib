// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// GitHub Pages project site: https://bot4ka.github.io/asockslib
// https://astro.build/config
export default defineConfig({
	site: 'https://bot4ka.github.io',
	base: '/asockslib',
	integrations: [
		starlight({
			title: {
				en: 'ASocks Docs',
				ru: 'ASocks Документация',
			},
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/bot4ka/asockslib' }],
			// English is the default (served at the site root); Russian lives under /ru.
			defaultLocale: 'root',
			locales: {
				root: { label: 'English', lang: 'en' },
				ru: { label: 'Русский', lang: 'ru' },
			},
			sidebar: [
				{
					label: 'Getting Started',
					translations: { ru: 'Начало работы' },
					items: [
						{ label: 'Quick Start', translations: { ru: 'Быстрый старт' }, slug: 'guides/quickstart' },
						{ label: 'Usage Examples', translations: { ru: 'Примеры использования' }, slug: 'guides/examples' },
						{ label: 'Key Concepts', translations: { ru: 'Основные понятия' }, slug: 'guides/concepts' },
						{ label: 'CLI Usage', translations: { ru: 'Использование CLI' }, slug: 'guides/cli' },
					],
				},
				{
					label: 'Proxy Management',
					translations: { ru: 'Управление прокси' },
					items: [
						{ label: 'Smart Proxy', translations: { ru: 'Smart Proxy' }, slug: 'guides/smart-proxy' },
						{ label: 'Proxy Pool', translations: { ru: 'Proxy Pool' }, slug: 'guides/proxy-pool' },
						{ label: 'Proxy Templates', translations: { ru: 'Шаблоны прокси' }, slug: 'guides/templates' },
					],
				},
				{
					label: 'API Reference',
					translations: { ru: 'Справочник API' },
					autogenerate: { directory: 'reference' },
				},
			],
		}),
	],
});
