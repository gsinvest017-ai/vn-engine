/**
 * VNScript Parser
 * Converts .vns text into an array of command objects.
 */

export function parseScript(text) {
  const lines = text.split('\n');
  const commands = [];
  let i = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trim();
    i++;
    const srcLine = i;  // 1-based 來源行號（供 dev preview / lint 對應）

    if (!line || line.startsWith('#')) continue;

    if (line.startsWith('@')) {
      const cmd = parseDirective(line.slice(1), lines, i);
      cmd.line = srcLine;
      if (cmd.type === 'choice') {
        // consume option lines
        const options = [];
        while (i < lines.length) {
          const opt = lines[i].trim();
          if (!opt.startsWith('>')) break;
          const arrow = opt.indexOf('->');
          const text  = arrow >= 0 ? opt.slice(1, arrow).trim() : opt.slice(1).trim();
          const label = arrow >= 0 ? opt.slice(arrow + 2).trim() : null;
          options.push({ text, label });
          i++;
        }
        cmd.options = options;
      }
      commands.push(cmd);
      continue;
    }

    if (line.startsWith('[')) {
      const bracketEnd = line.indexOf(']');
      if (bracketEnd > 0) {
        const charId = line.slice(1, bracketEnd).trim();
        const text   = line.slice(bracketEnd + 1).trim();
        commands.push({ type: 'dialogue', character: charId, text, line: srcLine });
        continue;
      }
    }

    if (line.startsWith('>')) {
      commands.push({ type: 'narration', text: line.slice(1).trim(), style: 'quote', line: srcLine });
      continue;
    }

    commands.push({ type: 'narration', text: line, style: 'normal', line: srcLine });
  }

  return commands;
}

function parseDirective(content) {
  const spaceIdx = content.search(/\s/);
  const cmd   = spaceIdx >= 0 ? content.slice(0, spaceIdx) : content;
  const rest  = spaceIdx >= 0 ? content.slice(spaceIdx + 1).trim() : '';
  const params = parseParams(rest);

  switch (cmd) {
    case 'chapter':
      return { type: 'chapter', title: rest };

    case 'scene':
      return {
        type: 'scene',
        bg: params.bg || null,
        music: params.music || null,
        sfx: params.sfx || null,
        transition: params.transition || 'fade',
      };

    case 'weather':
      return {
        type: 'weather',
        rain: params.rain || 'none',
        fog: parseFloat(params.fog || '0'),
        wind: parseFloat(params.wind || '0'),
      };

    case 'char': {
      // 注意：子指令格式是 `@char show=<id> ...`，firstToken 會拿到
      // "show=<id>" 而非 "show"——必須用 params key 判斷分支。
      // （舊版用 sub === 'show' 比對，導致所有 @char 指令都掉進
      //   char_raw no-op，立繪只剩對白自動上場 — 已修正）
      if (params.show) {
        return {
          type: 'char_show',
          id: params.show,
          pos: params.pos || 'center',
          expr: params.expr || 'normal',
        };
      }
      if (params.move) {
        return {
          type: 'char_move',
          id: params.move,
          pos: params.pos || 'center',
          duration: parseInt(params.duration || '400', 10),
        };
      }
      if (params.expr) {
        // @char expr=<id>:<expr>（無 show= 時才視為純表情變化）
        const exprVal = params.expr;
        const colon = exprVal.indexOf(':');
        const id    = colon >= 0 ? exprVal.slice(0, colon) : exprVal;
        const expr  = colon >= 0 ? exprVal.slice(colon + 1) : 'normal';
        return { type: 'char_expr', id, expr };
      }
      if (params.hide || firstToken(rest) === 'hide') {
        return { type: 'char_hide', id: params.hide || 'all' };
      }
      return { type: 'char_raw', params };
    }

    case 'sfx': {
      if (params.play)  return { type: 'sfx_play', id: params.play, volume: parseFloat(params.volume || '1'), loop: params.loop === 'true', delay: parseInt(params.delay || '0', 10) };
      if (params.stop)  return { type: 'sfx_stop', id: params.stop, fade: parseInt(params.fade || '0', 10) };
      return { type: 'sfx_raw', params };
    }

    case 'bgm': {
      if (params.play)  return { type: 'bgm_play', id: params.play, fade: parseInt(params.fade || '0', 10) };
      if (firstToken(rest) === 'stop') return { type: 'bgm_stop', fade: parseInt(params.fade || '0', 10) };
      if (params.volume !== undefined) return { type: 'bgm_volume', value: parseFloat(params.volume) };
      return { type: 'bgm_raw', params };
    }

    case 'effect': {
      const fx = firstToken(rest);
      return {
        type: 'effect',
        fx,
        intensity: parseFloat(params.intensity || '0.5'),
        level: parseFloat(params.level || '0.5'),
        duration: parseInt(params.duration || '500', 10),
        color: params.color || 'white',
        count: parseInt(params.count || '3', 10),
      };
    }

    case 'fade':
      return {
        type: 'fade',
        direction: firstToken(rest) || 'out',
        color: params.color || 'black',
        duration: parseInt(params.duration || '800', 10),
      };

    case 'wait':
      return { type: 'wait', ms: parseInt(rest, 10) || 500 };

    case 'pause':
      return { type: 'pause' };

    case 'set': {
      // @set key=value | @set key+=1（value 自動判型：number / true / false / 字串）
      const m = rest.match(/^(\w+)\s*(\+=|=)\s*(.+)$/);
      if (!m) return { type: 'unknown', raw: content };
      return { type: 'set', key: m[1], op: m[2], value: coerceValue(m[3].trim()) };
    }

    case 'if': {
      // @if key==value jump=label（op: == != >= <= > <）
      const m = rest.match(/^(\w+)\s*(==|!=|>=|<=|>|<)\s*("[^"]*"|\S+)\s+jump=(\S+)$/);
      if (!m) return { type: 'unknown', raw: content };
      return { type: 'if_jump', key: m[1], op: m[2], value: coerceValue(m[3]), label: m[4] };
    }

    case 'label':
      return { type: 'label', name: rest.trim() };

    case 'jump':
      return { type: 'jump', label: rest.trim() };

    case 'choice':
      return { type: 'choice', options: [] };

    case 'chapter_end':
      return { type: 'chapter_end' };

    case 'suspense_end':
      return {
        type: 'suspense_end',
        message:  params.message || '',
        duration: parseInt(params.duration || '5200', 10),
      };

    case 'end':
      return { type: 'end' };

    default:
      return { type: 'unknown', raw: content };
  }
}

function parseParams(str) {
  const params = {};
  const regex = /(\w+)=("([^"]*)"|\S+)/g;
  let m;
  while ((m = regex.exec(str)) !== null) {
    params[m[1]] = m[3] !== undefined ? m[3] : m[2];
  }
  return params;
}

function firstToken(str) {
  return str.trim().split(/\s+/)[0] || '';
}

/** @set / @if 的值自動判型：number / true / false / 去引號字串 */
function coerceValue(raw) {
  if (raw === 'true')  return true;
  if (raw === 'false') return false;
  if (/^-?\d+(\.\d+)?$/.test(raw)) return Number(raw);
  return raw.replace(/^"(.*)"$/, '$1');
}
