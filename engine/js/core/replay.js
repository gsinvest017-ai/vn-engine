/**
 * replay.js — 劇本指令的「累積狀態」重建（單一來源）。
 *
 * 三處共用：
 *   1. Dev preview（游標行 → 畫面狀態）
 *   2. 讀檔恢復（存檔 index → 重建背景/立繪/BGM/台詞）
 *   3. devLine 起跑（dashboard「從游標行開始玩」）
 *
 * 只重建「持續狀態」；瞬時指令（shake/flash/fade/wait）不納入。
 */

/**
 * 累積 commands 在界線之前的持續狀態。
 * @param {Array}  commands  parseScript 產出（可為 engine.allCommands）
 * @param {Object} opts
 * @param {number} opts.uptoIndex  含此 index（預設不限制）
 * @param {number} opts.uptoLine   含此來源行號（預設不限制）
 * @returns {{bg, weather, bgm, chars, text, dim, vignette, exprState, variables}}
 */
export function accumulateState(commands, { uptoIndex = Infinity, uptoLine = Infinity } = {}) {
  const st = {
    bg: null, weather: null, bgm: null,
    chars: {},                 // id → { pos, expr }
    text: null,                // { text, speaker, style, charId }
    dim: null, vignette: null,
    exprState: {},             // id → 最後表情（含未在場上）
    variables: {},             // @set 累積
  };
  for (let i = 0; i < commands.length; i++) {
    if (i > uptoIndex) break;
    const cmd = commands[i];
    if ((cmd.line || 0) > uptoLine) break;
    switch (cmd.type) {
      case 'scene':
        if (cmd.bg) st.bg = cmd.bg;
        if (cmd.music) st.bgm = cmd.music;
        break;
      case 'weather':
        st.weather = { rain: cmd.rain, fog: cmd.fog, wind: cmd.wind };
        break;
      case 'bgm_play':  st.bgm = cmd.id; break;
      case 'bgm_stop':  st.bgm = null; break;
      case 'char_show':
        st.chars[cmd.id] = { pos: cmd.pos, expr: cmd.expr };
        st.exprState[cmd.id] = cmd.expr;
        break;
      case 'char_hide':
        if (cmd.id === 'all') st.chars = {};
        else delete st.chars[cmd.id];
        break;
      case 'char_expr':
        if (st.chars[cmd.id]) st.chars[cmd.id].expr = cmd.expr;
        st.exprState[cmd.id] = cmd.expr;
        break;
      case 'char_move':
        if (st.chars[cmd.id]) st.chars[cmd.id].pos = cmd.pos;
        break;
      case 'effect':
        if (cmd.fx === 'dim' || cmd.fx === 'darkness') st.dim = cmd.fx === 'darkness' ? 0.92 : cmd.level;
        if (cmd.fx === 'vignette') st.vignette = cmd.intensity;
        if (cmd.fx === 'clear') { st.dim = null; st.vignette = null; }
        break;
      case 'set':
        applySet(st.variables, cmd);
        break;
      case 'dialogue': {
        if (cmd.character && !st.chars[cmd.character]) {
          st.chars[cmd.character] = { pos: 'center', expr: st.exprState[cmd.character] || 'normal' };
          st.exprState[cmd.character] ??= 'normal';
        }
        st.text = { text: cmd.text, speaker: cmd.character, style: 'dialogue', charId: cmd.character };
        break;
      }
      case 'narration':
        st.text = { text: cmd.text, speaker: '', style: cmd.style, charId: null };
        break;
      case 'chapter':
        st.text = { text: `【${cmd.title}】`, speaker: '', style: 'normal', charId: null };
        break;
    }
  }
  return st;
}

/** @set 的賦值語意（engine 與 replay 共用） */
export function applySet(variables, cmd) {
  if (cmd.op === '+=') {
    const cur = Number(variables[cmd.key] ?? 0);
    variables[cmd.key] = cur + Number(cmd.value);
  } else {
    variables[cmd.key] = cmd.value;
  }
}

/** @if 條件求值（engine 與 lint 共用） */
export function evalCondition(variables, cmd) {
  const cur = variables[cmd.key];
  const val = cmd.value;
  switch (cmd.op) {
    case '==': return cur == val;          // eslint-disable-line eqeqeq
    case '!=': return cur != val;          // eslint-disable-line eqeqeq
    case '>=': return Number(cur) >= Number(val);
    case '<=': return Number(cur) <= Number(val);
    case '>':  return Number(cur) >  Number(val);
    case '<':  return Number(cur) <  Number(val);
    default:   return false;
  }
}
