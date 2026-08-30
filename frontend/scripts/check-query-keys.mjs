/**
 * query key 的字面值只准出現在 src/lib/queryKeys.ts。
 *
 * 為什麼需要這條檢查、而不是靠 code review 或再加一支測試：query key 打錯
 * **不會報錯、不會壞畫面**。react-query 換一個 key 照樣呼叫同一個 queryFn，
 * 清單照樣載入；壞掉的只有「誰跟誰共用快取」與「invalidate 打得到誰」。實測
 * 過：把 LibraryPage 的 key 從 `['videos','library']` 改成 `['videos','libraryX']`，
 * 19 支 e2e smoke 有 18 支照樣綠燈（唯一抓到的是刪除那支，因為它驗 invalidation）。
 *
 * e2e 抓得到「invalidate 的 key 跟讀取的 key 不一致」，但抓不到「兩個元件各自
 * 用了不同卻都能運作的 key」——那只會多打一次 API，畫面上完全看不出來。那種
 * 情況只能從結構上禁止：不准在別的地方寫字面值，就不可能寫出不一致的兩份。
 *
 * 掛在 `npm run lint` 上。oxlint 這個版本沒有 no-restricted-syntax 之類可以
 * 表達這條規則的內建規則，所以獨立成一支腳本。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))
const ALLOWED = 'lib/queryKeys.ts'

/** 只比對「傳給 react-query 的 key」這三個位置，不是全檔搜尋陣列字面值——
 * 否則 `['字幕','畫面','OCR']` 這種一般常數也會被誤判。 */
const PATTERNS = [
  { name: 'queryKey:', re: /queryKey:\s*\[/g },
  { name: 'invalidateQueries', re: /invalidateQueries\(\{\s*queryKey:\s*\[/g },
  { name: 'setQueryData', re: /setQueryData\(\s*\[/g },
]

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) yield* walk(full)
    else if (/\.tsx?$/.test(full)) yield full
  }
}

const offences = []
for (const file of walk(SRC)) {
  const rel = relative(SRC, file).split('\\').join('/')
  if (rel === ALLOWED) continue
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, i) => {
    for (const { name, re } of PATTERNS) {
      re.lastIndex = 0
      if (re.test(line)) offences.push({ rel, line: i + 1, name, text: line.trim() })
    }
  })
}

if (offences.length > 0) {
  console.error(`\n✗ query key 字面值只能寫在 src/${ALLOWED}，發現 ${offences.length} 處：\n`)
  for (const o of offences) {
    console.error(`  src/${o.rel}:${o.line}  (${o.name})`)
    console.error(`    ${o.text}\n`)
  }
  console.error(`改法：在 src/${ALLOWED} 加一個具名的 key 函式，然後在這裡呼叫它。\n`)
  process.exit(1)
}

console.log(`✓ query key 字面值都收在 src/${ALLOWED}`)
