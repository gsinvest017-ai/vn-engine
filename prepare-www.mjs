// prepare-www.mjs — 重建 Capacitor 的 webDir (www/)。
// www/ 是 build 產物（不進 git）：把純靜態的遊戲檔案彙整成一個乾淨資料夾，
// 排除 .git / node_modules / android / tests 等，供 `npx cap copy android` 打包。
// 用法：npm run build:www  （或 npm run cap:sync 一併 cap copy）
import { cpSync, rmSync, mkdirSync } from 'node:fs';

const WWW = 'www';
const ITEMS = ['index.html', 'engine', 'assets', 'scripts'];

rmSync(WWW, { recursive: true, force: true });
mkdirSync(WWW, { recursive: true });
for (const item of ITEMS) {
  cpSync(item, `${WWW}/${item}`, { recursive: true });
}
console.log(`www/ 重建完成（${ITEMS.join(', ')}）`);
