/**
 * workdir 解析单测（GRAFT-2 修复，2026-10-04）。
 *
 * 背景：python 子进程此前固定 cwd=插件 python 目录，工具参数的相对路径
 * （如 graft_design 的 sequence='lacZ_first_third.fasta'）解析到插件目录、
 * 报「文件不存在」（实战测试中 agent 被迫改用绝对路径自愈）。
 * 修复：resolveWorkdir(exec) 解析会话工作区，作为 callGraft 的 spawn cwd。
 *
 * 变异锚点：让 resolveWorkdir 忽略 exec 直接返回保底目录，本测试必须报红。
 */
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fallbackWorkspace, resolveWorkdir, sessionWorkspace } from '../src/workdir.js'

let passed = 0

function test(name, run) {
  run()
  passed += 1
  console.log(`  ok   ${name}`)
}

const tmp = mkdtempSync(join(homedir(), '.dsh', 'graft-workdir-test-'))
try {
  test('会话 cwd 优先（resolveWorkdir 采用 exec.agent.session.header.cwd）', () => {
    const fakeExec = { agent: { session: { header: { cwd: tmp } } } }
    assert.equal(resolveWorkdir(fakeExec), tmp)
    assert.equal(sessionWorkspace(fakeExec), tmp)
  })

  test('server cwd（process.cwd()）视为未指定 → 走保底', () => {
    const serverExec = { agent: { session: { header: { cwd: process.cwd() } } } }
    assert.equal(resolveWorkdir(serverExec), fallbackWorkspace())
  })

  test('无 exec → 保底工作区', () => {
    assert.equal(resolveWorkdir(undefined), fallbackWorkspace())
    assert.equal(resolveWorkdir({}), fallbackWorkspace())
  })

  test('会话 cwd 不存在（不可读）→ 保底工作区', () => {
    const gone = { agent: { session: { header: { cwd: join(tmp, 'no-such-dir') } } } }
    assert.equal(sessionWorkspace(gone), undefined)
    assert.equal(resolveWorkdir(gone), fallbackWorkspace())
  })

  test('保底工作区自动创建', () => {
    const fb = resolveWorkdir(undefined)
    assert.ok(existsSync(fb), `保底工作区应存在：${fb}`)
  })

  console.log(`workdir: ${passed} passed, 0 failed`)
} finally {
  rmSync(tmp, { recursive: true, force: true })
}
