// version.js — 插件身份的单一事实源。
//
// 修正背景（D9）：integration.js 曾把 '0.1.0' 硬编码在常量里——版本一 bump 就漂移，
// 宿主面板与 agent 都会读到过期版本号。版本只能有一个来源：package.json。
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PKG = JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', 'package.json'), 'utf8'))

export const PLUGIN_ID = PKG.name          // '@dsh-bio/dsh-bio-graft'
export const PLUGIN_VERSION = PKG.version
