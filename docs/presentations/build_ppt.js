/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');
const PptxGenJS = require('pptxgenjs');
const sharp = require('sharp');

const ROOT = __dirname;
const SOURCE_DIR = path.join(ROOT, 'source');
const PREVIEW_DIR = path.join(ROOT, 'previews');
const PPT_PATH = path.join(ROOT, '企业智能体平台架构与业务闭环.pptx');

const W = 1600;
const H = 900;
const FONT = 'Microsoft YaHei, PingFang SC, Noto Sans CJK SC, WenQuanYi Zen Hei, sans-serif';

const C = {
  navy: '#0B1F33',
  navy2: '#173A5E',
  text: '#18324A',
  muted: '#65788A',
  line: '#C9D4DF',
  bg: '#F5F7FA',
  white: '#FFFFFF',
  blue: '#2F6FED',
  blueLight: '#EAF2FF',
  purple: '#7357D8',
  purpleLight: '#F0ECFF',
  green: '#149B72',
  greenLight: '#E8F8F2',
  amber: '#D89A23',
  amberLight: '#FFF6DF',
  orange: '#E6772E',
  orangeLight: '#FFF0E5',
  red: '#D95454',
  redLight: '#FFF0F0',
  teal: '#258C9B',
  tealLight: '#E8F6F8',
  grayLight: '#EEF2F6',
};

function esc(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function rect(x, y, w, h, fill = C.white, stroke = 'none', rx = 18, sw = 1.5, extra = '') {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
}

function circle(cx, cy, r, fill, stroke = 'none', sw = 1.5, extra = '') {
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
}

function line(x1, y1, x2, y2, color = C.navy2, sw = 2, marker = '', dash = '') {
  const mk = marker ? ` marker-end="url(#${marker})"` : '';
  const ds = dash ? ` stroke-dasharray="${dash}"` : '';
  return `<path d="M${x1} ${y1} L${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${sw}"${mk}${ds}/>`;
}

function pathLine(d, color = C.navy2, sw = 2, marker = '', dash = '') {
  const mk = marker ? ` marker-end="url(#${marker})"` : '';
  const ds = dash ? ` stroke-dasharray="${dash}"` : '';
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${sw}"${mk}${ds}/>`;
}

function text(x, y, lines, opts = {}) {
  const arr = Array.isArray(lines) ? lines : [lines];
  const size = opts.size || 24;
  const lh = opts.lh || Math.round(size * 1.35);
  const anchor = opts.anchor || 'start';
  const fill = opts.fill || C.text;
  const weight = opts.weight || 400;
  const opacity = opts.opacity == null ? 1 : opts.opacity;
  const style = opts.italic ? 'font-style="italic"' : '';
  const tspans = arr.map((v, i) => `<tspan x="${x}" y="${y + i * lh}">${esc(v)}</tspan>`).join('');
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" opacity="${opacity}" ${style}>${tspans}</text>`;
}

function pill(x, y, w, label, fill, color = C.text, stroke = 'none') {
  return rect(x, y, w, 38, fill, stroke, 19, 1.2) + text(x + w / 2, y + 26, label, { size: 18, weight: 700, fill: color, anchor: 'middle' });
}

function card(x, y, w, h, title, body, opts = {}) {
  const fill = opts.fill || C.white;
  const stroke = opts.stroke || C.line;
  const titleColor = opts.titleColor || C.text;
  const bodyColor = opts.bodyColor || C.muted;
  const icon = opts.icon;
  let out = rect(x, y, w, h, fill, stroke, opts.rx || 18, opts.sw || 1.5, opts.shadow === false ? '' : 'filter="url(#shadow)"');
  let titleX = x + 24;
  if (icon) {
    out += circle(x + 34, y + 34, 20, opts.iconFill || stroke);
    out += text(x + 34, y + 41, icon, { size: 18, weight: 800, fill: C.white, anchor: 'middle' });
    titleX = x + 64;
  }
  out += text(titleX, y + 37, title, { size: opts.titleSize || 22, weight: 700, fill: titleColor });
  if (body) out += text(x + 24, y + 72, body, { size: opts.bodySize || 17, lh: opts.bodyLh || 25, fill: bodyColor });
  return out;
}

function smallNode(x, y, w, h, title, lines, color, light) {
  return rect(x, y, w, h, light, color, 16, 1.6, 'filter="url(#shadow)"') +
    text(x + w / 2, y + 37, title, { size: 21, weight: 700, fill: color, anchor: 'middle' }) +
    text(x + w / 2, y + 69, lines, { size: 16, lh: 23, fill: C.muted, anchor: 'middle' });
}

function diamond(cx, cy, w, h, fill, stroke, label, sub = '') {
  const pts = `${cx},${cy - h / 2} ${cx + w / 2},${cy} ${cx},${cy + h / 2} ${cx - w / 2},${cy}`;
  let out = `<polygon points="${pts}" fill="${fill}" stroke="${stroke}" stroke-width="2" filter="url(#shadow)"/>`;
  out += text(cx, cy - (sub ? 7 : -7), label, { size: 20, weight: 800, fill: stroke, anchor: 'middle' });
  if (sub) out += text(cx, cy + 21, sub, { size: 14, fill: C.muted, anchor: 'middle' });
  return out;
}

function defs() {
  return `<defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#0B1F33" flood-opacity="0.10"/></filter>
    <marker id="arrowNavy" markerWidth="11" markerHeight="11" refX="9" refY="4" orient="auto"><path d="M0,0 L0,8 L10,4 z" fill="${C.navy2}"/></marker>
    <marker id="arrowBlue" markerWidth="11" markerHeight="11" refX="9" refY="4" orient="auto"><path d="M0,0 L0,8 L10,4 z" fill="${C.blue}"/></marker>
    <marker id="arrowGreen" markerWidth="11" markerHeight="11" refX="9" refY="4" orient="auto"><path d="M0,0 L0,8 L10,4 z" fill="${C.green}"/></marker>
    <marker id="arrowOrange" markerWidth="11" markerHeight="11" refX="9" refY="4" orient="auto"><path d="M0,0 L0,8 L10,4 z" fill="${C.orange}"/></marker>
    <marker id="arrowRed" markerWidth="11" markerHeight="11" refX="9" refY="4" orient="auto"><path d="M0,0 L0,8 L10,4 z" fill="${C.red}"/></marker>
  </defs>`;
}

function svgWrap(content, title) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">
${defs()}<rect width="${W}" height="${H}" fill="${C.bg}"/>${content}</svg>`;
}

function frame(no, title, subtitle = '') {
  let out = `<rect x="0" y="0" width="18" height="900" fill="${C.blue}"/>`;
  out += text(72, 58, title, { size: 34, weight: 800, fill: C.navy });
  if (subtitle) out += text(72, 91, subtitle, { size: 17, fill: C.muted });
  out += line(72, 116, 1528, 116, C.line, 1.3);
  out += text(72, 872, '企业智能体平台架构与业务闭环', { size: 14, fill: '#8797A6' });
  out += text(1528, 872, String(no).padStart(2, '0'), { size: 14, weight: 700, fill: '#8797A6', anchor: 'end' });
  return out;
}

function labelArrow(x1, y1, x2, y2, label, color = C.navy2, opts = {}) {
  let out = line(x1, y1, x2, y2, color, opts.sw || 2.3, opts.marker || 'arrowNavy', opts.dash || '');
  if (label) out += pill((x1 + x2) / 2 - (opts.labelW || 70) / 2, (y1 + y2) / 2 - 42, opts.labelW || 70, label, C.white, color, C.line);
  return out;
}

function factTag(label, color, light, w = 168) {
  return pill(1528 - w, 36, w, label, light, color, color);
}

function coverSlide() {
  let c = `<rect width="1600" height="900" fill="${C.navy}"/>`;
  c += `<circle cx="1370" cy="-50" r="420" fill="#173A5E" opacity="0.75"/>`;
  c += `<circle cx="1470" cy="850" r="330" fill="#102B47" opacity="0.85"/>`;
  c += pill(88, 98, 410, '目标运行架构 · DDD 边界 · 当前实现', '#173A5E', '#CDE0F4');
  c += text(88, 236, ['企业智能体平台', '架构与业务闭环'], { size: 64, lh: 82, weight: 800, fill: C.white });
  c += text(92, 427, ['从业务意图到受控行动', '从执行结果到可治理演进'], { size: 27, lh: 39, fill: '#C9D8E8' });
  c += text(92, 792, 'AI-Youdoogo · 架构语义校准版', { size: 18, fill: '#9FB5CA' });

  const bx = 960, bw = 430, bh = 82;
  const layers = [
    ['1', '意图与结果层', '目标 · 约束 · 预期结果', C.blue, C.blueLight],
    ['2', '中枢编排层', '拆解 · 路由 · 协调', C.purple, C.purpleLight],
    ['3', '业务执行与技能层', '智能体 · 真人 · 企业能力', C.green, C.greenLight],
    ['4', '上下文与记忆层', '事实 · 来源 · 版本 · 受控读取', C.amber, C.amberLight],
  ];
  layers.forEach((it, i) => {
    const y = 176 + i * 112;
    c += rect(bx, y, bw, bh, it[4], 'none', 20, 0, 'filter="url(#shadow)"');
    c += circle(bx + 48, y + 41, 25, it[3]);
    c += text(bx + 48, y + 49, it[0], { size: 22, weight: 800, fill: C.white, anchor: 'middle' });
    c += text(bx + 88, y + 34, it[1], { size: 23, weight: 800, fill: C.navy });
    c += text(bx + 88, y + 61, it[2], { size: 16, fill: C.muted });
    if (i < 3) c += line(bx + bw / 2, y + bh, bx + bw / 2, y + 112, '#7F96AC', 2, 'arrowNavy');
  });
  c += pill(930, 650, 235, '反馈闭环', C.orangeLight, C.orange, C.orange);
  c += pill(1180, 650, 270, '控制与保障面', C.redLight, C.red, C.red);
  return svgWrap(c, '企业智能体平台架构与业务闭环');
}

function slide2() {
  let c = frame(2, '先分清三种架构视图', '同一套实现需要从三个正交视图描述，禁止再用一张“分层图”混为一谈');
  c += factTag('阅读规则', C.blue, C.blueLight);
  const xs = [90, 545, 1000];
  const data = [
    ['01', '系统运行视图', [['结构：四层运行链路', '+ 两个横切系统'], ['回答：目标如何被接收、规划、', '执行、治理和反馈'], ['不直接对应源码目录']], C.blue, C.blueLight],
    ['02', 'DDD 领域视图', [['结构：业务 Context、基础底座 Context', '与 Context Map'], ['回答：规则、状态、数据和', '公开语言归谁所有'], ['只对应具有独立所有权的', '叶子 Context']], C.purple, C.purpleLight],
    ['03', '代码依赖视图', [['结构：Context 内五层', '+ Platform + Bootstrap'], ['回答：源码依赖方向和', '技术实现归属'], ['直接约束目录与 import']], C.green, C.greenLight],
  ];
  data.forEach((d, i) => {
    c += rect(xs[i], 175, 410, 438, C.white, d[3], 24, 2, 'filter="url(#shadow)"');
    c += circle(xs[i] + 60, 235, 34, d[3]);
    c += text(xs[i] + 60, 244, d[0], { size: 24, weight: 800, fill: C.white, anchor: 'middle' });
    c += text(xs[i] + 112, 246, d[1], { size: 29, weight: 800, fill: C.navy });
    c += rect(xs[i] + 34, 292, 342, 2, d[3], 'none', 0, 0);
    d[2].forEach((cLine, j) => {
      c += circle(xs[i] + 56, 342 + j * 80, 7, d[3]);
      c += text(xs[i] + 78, 347 + j * 80, cLine, { size: 16, lh: 22, weight: 600, fill: C.text });
    });
    c += rect(xs[i] + 34, 542, 342, 45, d[4], 'none', 13, 0);
    c += text(xs[i] + 205, 572, i === 0 ? '运行责任，不是目录' : i === 1 ? '所有权边界' : '源码依赖规则', { size: 19, weight: 800, fill: d[3], anchor: 'middle' });
  });
  c += rect(170, 675, 1260, 100, C.navy, 'none', 22, 0);
  c += text(800, 716, '常见错误：把运行层误建成同名大包，或把全部编排职责收进一个万能服务', { size: 22, weight: 800, fill: C.white, anchor: 'middle' });
  c += text(800, 753, '三种视图要分别表达，再通过契约、端口和事件建立对应关系', { size: 19, fill: '#C9D8E8', anchor: 'middle' });
  return svgWrap(c, '三种架构视图');
}

function slide3() {
  let c = frame(3, '目标运行架构：四层主链路 + 两个横切系统', '这是运行责任视图，不等于四个目录、四个服务、四个进程或四个数据库');
  c += factTag('目标规范', C.blue, C.blueLight);
  c += rect(92, 170, 170, 555, C.orangeLight, C.orange, 26, 2);
  c += text(177, 225, ['反馈闭环', '业务结果与改进'], { size: 23, lh: 31, weight: 800, fill: C.orange, anchor: 'middle' });
  c += text(177, 315, ['业务结果', '验收意见', '失败原因', '异常告警', '人工评分'], { size: 18, lh: 48, weight: 600, fill: C.text, anchor: 'middle' });
  c += pathLine('M177 650 C177 785 510 790 510 705', C.orange, 3, 'arrowOrange', '8 7');

  c += rect(1338, 170, 170, 555, C.redLight, C.red, 26, 2);
  c += text(1423, 225, ['控制与保障面', '全程强制护栏'], { size: 22, lh: 31, weight: 800, fill: C.red, anchor: 'middle' });
  c += text(1423, 315, ['身份', '权限', '数据范围', '能力与风险', '审批', '凭据与审计'], { size: 18, lh: 42, weight: 600, fill: C.text, anchor: 'middle' });
  c += text(1423, 620, ['横切所有调用', '高风险默认拒绝'], { size: 16, lh: 27, weight: 700, fill: C.red, anchor: 'middle' });

  const x = 315, w = 970, h = 106;
  const layers = [
    [176, C.blueLight, C.blue, '1', '意图与结果层', '接收主体、业务目标、预期结果、约束与引用；交付结果、证据和待确认事项'],
    [306, C.purpleLight, C.purple, '2', '中枢编排层', '基于受控上下文完成规划、分派、运行协调、恢复和结果汇总'],
    [436, C.greenLight, C.green, '3', '业务执行与技能层', '智能体、真人或企业能力执行步骤；所有副作用通过受治理能力契约'],
    [566, C.amberLight, C.amber, '4', '上下文与记忆层', '统一的受治理查询与上下文装配入口；来源 Context 仍拥有原始事实'],
  ];
  layers.forEach((d, i) => {
    c += rect(x, d[0], w, h, d[1], d[2], 22, 2, 'filter="url(#shadow)"');
    c += circle(x + 55, d[0] + 53, 30, d[2]);
    c += text(x + 55, d[0] + 62, d[3], { size: 25, weight: 800, fill: C.white, anchor: 'middle' });
    c += text(x + 104, d[0] + 43, d[4], { size: 26, weight: 800, fill: C.navy });
    c += text(x + 104, d[0] + 76, d[5], { size: 17, fill: C.muted });
    if (i < 2) c += line(800, d[0] + h, 800, layers[i + 1][0], C.navy2, 2.4, 'arrowNavy');
  });
  c += pathLine('M1040 566 C1190 530 1190 260 1040 282', C.amber, 2.2, 'arrowOrange', '7 6');
  c += text(1163, 413, ['按权限和用途', '提供上下文快照'], { size: 15, lh: 22, weight: 700, fill: C.amber, anchor: 'middle' });
  c += rect(315, 720, 970, 54, C.navy, 'none', 16, 0);
  c += text(800, 755, '控制面在关键节点强制检查；反馈闭环消费结果与证据——它们不是六个串行服务', { size: 19, weight: 700, fill: C.white, anchor: 'middle' });
  return svgWrap(c, '总体架构');
}

function slide4() {
  let c = frame(4, '端到端规范主链路', '使用正式契约串起目标接入、上下文装配、规划、执行、结果交付和受控改进');
  c += factTag('目标规范', C.blue, C.blueLight);
  c += rect(92, 155, 1416, 72, C.amberLight, C.amber, 18, 1.5);
  c += text(120, 188, '上下文与记忆层', { size: 20, weight: 800, fill: C.amber });
  c += text(345, 188, '全程提供带权限、来源、版本、缺失信息和过期策略的 ContextSnapshot', { size: 18, fill: C.text });

  const nodes = [
    ['1', '目标接入', ['主体 + 目标 + 约束', '形成 IntentEnvelope'], C.blue, C.blueLight],
    ['2', '装配上下文', ['ContextQuery', '返回 ContextSnapshot'], C.amber, C.amberLight],
    ['3', '规划并启动', ['WorkIntent → WorkflowPlan', '检查能力 / 权限 / 真人节点', '通过后创建 WorkflowRun'], C.purple, C.purpleLight],
    ['4', '执行步骤', ['Agent / 真人 / Capability', '返回结果与证据'], C.green, C.greenLight],
    ['5', '交付结果', ['ResultEnvelope', '产物 + 引用 + 待确认项'], C.teal, C.tealLight],
    ['6', '形成改进候选', ['Outcome / Review', 'Evaluation → Candidate'], C.orange, C.orangeLight],
  ];
  const nx = [85, 330, 575, 820, 1065, 1310];
  nodes.forEach((d, i) => {
    const x = nx[i];
    c += rect(x, 294, 190, 206, C.white, d[3], 20, 2, 'filter="url(#shadow)"');
    c += circle(x + 95, 334, 25, d[3]);
    c += text(x + 95, 342, d[0], { size: 21, weight: 800, fill: C.white, anchor: 'middle' });
    c += text(x + 95, 390, d[1], { size: 21, weight: 800, fill: d[3], anchor: 'middle' });
    c += text(x + 95, 438, d[2], { size: 15, lh: 26, fill: C.muted, anchor: 'middle' });
    if (i < nodes.length - 1) c += line(x + 190, 397, nx[i + 1] - 8, 397, C.navy2, 2.5, 'arrowNavy');
  });

  c += rect(130, 575, 1340, 110, C.redLight, C.red, 20, 1.6);
  c += text(800, 613, '控制与保障面横切检查', { size: 22, weight: 800, fill: C.red, anchor: 'middle' });
  c += text(800, 649, '主体身份 · 访问决策 · 能力版本 · 风险/副作用 · 审批凭证 · 凭据范围 · 证据 · 审计', { size: 18, weight: 700, fill: C.text, anchor: 'middle' });
  c += text(800, 721, '改进候选必须经过评估、必要审批和版本发布，不能直接回写生产配置', { size: 19, weight: 800, fill: C.orange, anchor: 'middle' });
  c += text(800, 755, '每次调用携带 principal / tenant / trace / workflow / step / attempt / version 等必要关联标识', { size: 17, weight: 700, fill: C.orange, anchor: 'middle' });
  return svgWrap(c, '端到端主链路');
}

function slide5() {
  let c = frame(5, '中枢编排层：逻辑角色不等于 DDD Context', '【目标规范】运行角色描述“做什么”；Context 定义“谁拥有规则、状态和写入权”');
  c += factTag('目标规范', C.purple, C.purpleLight);
  c += text(75, 166, '运行角色：逻辑职责', { size: 24, weight: 800, fill: C.navy });
  const roles = [
    [70, 205, '监督者（Supervisor）', ['保持目标、约束', '和全局完成条件'], C.purple, C.purpleLight],
    [395, 205, '任务拆解 / 规划', ['把意图转为可验证的', 'WorkflowPlan'], C.blue, C.blueLight],
    [70, 355, '路由 / 分派', ['按能力、范围、风险、成本', '和可用性选择执行者'], C.teal, C.tealLight],
    [395, 355, '结果汇总', ['按步骤证据整理结果', '不能补造缺失事实'], C.green, C.greenLight],
  ];
  roles.forEach(d => c += smallNode(d[0], d[1], 285, 112, d[2], d[3], d[4], d[5]));

  c += pathLine('M705 260 C760 260 760 260 820 260', C.navy2, 2.5, 'arrowNavy', '7 6');
  c += pathLine('M705 410 C760 410 760 410 820 410', C.navy2, 2.5, 'arrowNavy', '7 6');
  c += text(765, 230, '由多个 Context', { size: 15, weight: 700, fill: C.muted, anchor: 'middle' });
  c += text(765, 252, '共同承载', { size: 15, weight: 700, fill: C.muted, anchor: 'middle' });

  c += text(835, 166, 'DDD Context：状态与所有权', { size: 24, weight: 800, fill: C.navy });
  const owners = [
    [820, 205, '工作规划', ['拥有 WorkIntent、WorkflowPlan', '规划策略与计划校验'], C.blue, C.blueLight],
    [1175, 205, '工作流运行', ['拥有 WorkflowRun / Step', 'DAG、租约、重试、恢复、真人停点'], C.purple, C.purpleLight],
    [820, 380, '任务管理', ['拥有 TaskCard', '分配、汇报、验收与驳回'], C.green, C.greenLight],
    [1175, 380, '来源业务 Context', ['拥有业务规则和原始事实', '作出最终业务生效决定'], C.red, C.redLight],
  ];
  owners.forEach(d => c += smallNode(d[0], d[1], 320, 128, d[2], d[3], d[4], d[5]));

  c += rect(100, 585, 1400, 96, C.navy, 'none', 20, 0);
  c += text(800, 621, '规范协作链', { size: 20, weight: 800, fill: '#AFC8E1', anchor: 'middle' });
  c += text(800, 655, 'IntentEnvelope + ContextSnapshot → 工作规划 → 工作流运行 → 智能体 / 企业能力 / 真人任务', { size: 20, weight: 800, fill: C.white, anchor: 'middle' });
  c += rect(175, 720, 1250, 70, C.redLight, C.red, 17, 1.5);
  c += text(800, 751, '边界：编排层不直接读取其他 Context 的 ORM，不直连供应商 SDK，也不绕过权限、幂等和审批', { size: 18, weight: 800, fill: C.red, anchor: 'middle' });
  return svgWrap(c, '中枢编排层');
}

function slide6() {
  let c = frame(6, '业务执行与技能层：三类执行路径不能混为一条', '【目标规范】真人任务由任务管理承载；只有智能体行动或直接能力步骤进入能力执行门禁');
  c += factTag('目标规范', C.green, C.greenLight);
  c += smallNode(55, 330, 175, 118, 'WorkflowStep', ['步骤输入、trace', '执行者和验收要求'], C.purple, C.purpleLight);
  c += line(230, 389, 285, 389, C.navy2, 2.5, 'arrowNavy');
  c += diamond(370, 389, 170, 112, C.grayLight, C.navy2, '分派给谁？');

  const assignees = [
    [490, 180, '智能体执行', ['使用 ExpertSnapshot', '需要行动时调用能力门禁'], C.blue, C.blueLight],
    [490, 340, '真人任务', ['任务管理负责分配、汇报', '真人验收或驳回'], C.green, C.greenLight],
    [490, 500, '直接能力步骤', ['工作流运行直接发起', 'CapabilityInvocation'], C.purple, C.purpleLight],
  ];
  assignees.forEach(d => c += smallNode(d[0], d[1], 270, 105, d[2], d[3], d[4], d[5]));
  c += pathLine('M455 389 L470 389 L470 232 L490 232', C.blue, 2, 'arrowBlue');
  c += line(455, 389, 490, 392, C.green, 2, 'arrowGreen');
  c += pathLine('M455 389 L470 389 L470 552 L490 552', C.purple, 2, 'arrowNavy');

  c += rect(820, 190, 320, 300, C.redLight, C.red, 22, 2, 'filter="url(#shadow)"');
  c += text(980, 234, '能力执行门禁', { size: 27, weight: 800, fill: C.red, anchor: 'middle' });
  c += text(980, 279, ['读取 CapabilityDefinition', '校验主体、Expert、参数和数据范围', '核验风险、审批凭证与能力版本', '记录 ToolExecution 幂等与重放', '归一结果、回执和审计引用'], { size: 16, lh: 34, weight: 600, fill: C.text, anchor: 'middle' });
  c += pathLine('M760 232 C790 232 790 280 820 280', C.blue, 2.2, 'arrowBlue');
  c += pathLine('M760 552 C790 552 790 410 820 410', C.purple, 2.2, 'arrowNavy');
  c += pathLine('M760 250 L785 250 L785 650 L720 680', C.blue, 1.8, 'arrowBlue', '7 6');
  c += text(805, 634, '无需能力调用时直接返回', { size: 14, weight: 700, fill: C.blue, anchor: 'middle' });

  const caps = [
    [1190, 160, '业务 Context 用例', '由所属 Context 重新校验并改变业务状态'],
    [1190, 290, '连接器 / 数据查询', '连接器执行或受治理数据查询'],
    [1190, 420, '交付 / 协作能力', '交付物管理与协作请求'],
    [1190, 550, '技术适配', 'HTTP / MCP / Sandbox 只实现端口'],
  ];
  caps.forEach(d => c += smallNode(d[0], d[1], 350, 92, d[2], [d[3]], C.teal, C.tealLight));
  c += line(1140, 340, 1190, 206, C.teal, 2, 'arrowNavy');
  c += line(1140, 340, 1190, 336, C.teal, 2, 'arrowNavy');
  c += line(1140, 340, 1190, 466, C.teal, 2, 'arrowNavy');
  c += line(1365, 382, 1365, 550, C.teal, 2.2, 'arrowNavy');

  c += pathLine('M625 445 L625 680', C.green, 2.2, 'arrowGreen');
  c += pathLine('M980 490 L980 680', C.red, 2.2, 'arrowRed');
  c += rect(235, 680, 1130, 108, C.navy, 'none', 20, 0);
  c += text(800, 719, '步骤回执返回工作流运行', { size: 20, weight: 800, fill: '#AFC8E1', anchor: 'middle' });
  c += text(800, 751, '智能体执行结果 / 任务验收或驳回事件 / CapabilityResult + Evidence', { size: 18, weight: 800, fill: C.white, anchor: 'middle' });
  c += text(800, 778, '发现了 Tool 或 MCP 能力，不等于主体已经获得执行授权', { size: 16, fill: '#BDD0E2', anchor: 'middle' });
  return svgWrap(c, '业务执行与技能层');
}

function slide7() {
  let c = frame(7, '上下文与记忆系统（Context System / Memory）：统一受治理入口', '“唯一共同知识源”指统一查询、权限、语义、引用和上下文组装，不表示共享写库或集中拥有全部事实');
  c += factTag('目标规范', C.amber, C.amberLight);
  c += text(85, 166, '来源 Context 与企业系统：各自拥有原始事实和写入规则', { size: 22, weight: 800, fill: C.navy });
  const contexts = [
    [85, 205, '提案管理', ['提案、评审、状态'], C.blue, C.blueLight],
    [85, 320, '会议管理', ['会议、投票、决议'], C.purple, C.purpleLight],
    [85, 435, '工作流运行 / 任务管理', ['运行状态、任务与验收'], C.green, C.greenLight],
    [85, 550, '助理会话 / 运营分析', ['对话归档、指标与异常'], C.teal, C.tealLight],
  ];
  contexts.forEach(d => c += smallNode(d[0], d[1], 300, 90, d[2], d[3], d[4], d[5]));

  c += rect(475, 180, 650, 500, C.white, C.amber, 26, 2, 'filter="url(#shadow)"');
  c += text(800, 225, '环境投影（Environment Projection）', { size: 27, weight: 800, fill: C.amber, anchor: 'middle' });
  c += text(800, 255, '围绕一次任务构造 ContextSnapshot', { size: 18, fill: C.muted, anchor: 'middle' });
  const pipeline = [
    [535, 310, 'ContextQuery', ['主体 · 用途 · 引用', '时间范围 · Token 预算']],
    [755, 310, '权限与检索', ['访问控制', 'RAG · 语义检索 · 数据查询']],
    [975, 310, '快照装配', ['事实 · 引用 · 版本', '缺失项 · 有效期']],
  ];
  pipeline.forEach((d, i) => {
    c += smallNode(d[0], d[1], 180, 145, d[2], d[3], C.amber, C.amberLight);
    if (i < 2) c += line(d[0] + 180, 382, pipeline[i + 1][0], 382, C.amber, 2.2, 'arrowOrange');
  });
  c += rect(560, 515, 480, 105, C.navy, 'none', 18, 0);
  c += text(800, 551, 'ContextSnapshot', { size: 24, weight: 800, fill: C.white, anchor: 'middle' });
  c += text(800, 584, ['主体/范围 · 来源引用 · 版本/时间 · 用途', '事实 · 缺失信息 · 敏感级别 · expires_at'], { size: 17, lh: 26, fill: '#C9D8E8', anchor: 'middle' });
  contexts.forEach(d => c += line(385, d[1] + 45, 475, 390, d[4], 1.8, 'arrowNavy', '6 5'));

  c += text(1210, 166, '参与快照装配的协作 Context', { size: 22, weight: 800, fill: C.navy });
  c += card(1190, 205, 335, 420, '协作能力', ['组织结构 / 专家管理', 'Wiki / 知识检索', '语义目录 / 组织记忆', '受治理数据查询', '访问控制'], { stroke: C.amber, fill: C.amberLight, icon: '知', iconFill: C.amber, bodySize: 18, bodyLh: 45 });
  c += line(1190, 410, 1125, 410, C.amber, 2.2, 'arrowOrange');
  c += rect(185, 730, 1230, 64, C.redLight, C.red, 16, 1.5);
  c += text(800, 770, '红线：模型生成的推断、摘要和建议必须标注类型与置信度，不能自动升级为企业事实', { size: 20, weight: 800, fill: C.red, anchor: 'middle' });
  return svgWrap(c, 'Context System / Memory');
}

function slide8() {
  let c = frame(8, '控制与安全保障面：贯穿意图、计划、执行、交付和反馈', '【目标规范】控制面由多个治理 Context 与 Platform 机制组合，不是一个万能“安全服务”');
  c += factTag('目标规范', C.red, C.redLight);
  const cead = [
    ['主体身份', C.blue, C.blueLight], ['角色 / 属性策略', C.purple, C.purpleLight],
    ['数据范围', C.teal, C.tealLight], ['能力编号 + 版本', C.green, C.greenLight],
    ['风险 / 副作用', C.orange, C.orangeLight], ['审批要求', C.red, C.redLight],
    ['凭据范围', C.amber, C.amberLight], ['证据 / 审计', C.navy2, C.grayLight],
  ];
  cead.forEach((d, i) => {
    const x = 55 + i * 193;
    c += rect(x, 175, 165, 72, d[2], d[1], 16, 1.6);
    c += text(x + 82, 219, d[0], { size: 16, weight: 800, fill: d[1], anchor: 'middle' });
    if (i < cead.length - 1) c += line(x + 165, 211, x + 188, 211, C.navy2, 2, 'arrowNavy');
  });
  c += text(70, 290, '六个强制控制点', { size: 23, weight: 800, fill: C.navy });
  const points = [
    [70, 325, '1  意图接入', ['认证主体与组织范围', '检查输入内容和风险提示'], C.blue, C.blueLight],
    [565, 325, '2  计划生成', ['逐步校验可授权性', '真人节点、预算与能力可用性'], C.purple, C.purpleLight],
    [1060, 325, '3  能力执行', ['重新校验主体、能力和参数', '数据范围、幂等和审批凭证'], C.red, C.redLight],
    [70, 515, '4  外部副作用', ['使用最小范围 CredentialRef', '禁止模型接触明文密钥'], C.orange, C.orangeLight],
    [565, 515, '5  结果交付', ['事实引用与敏感数据脱敏', '内容安全和外发策略'], C.teal, C.tealLight],
    [1060, 515, '6  反馈升级', ['评估集、策略版本和审批', '灰度发布、持续监测和回滚'], C.green, C.greenLight],
  ];
  points.forEach(p => c += smallNode(p[0], p[1], 420, 135, p[2], p[3], p[4], p[5]));
  c += rect(155, 720, 1290, 74, C.redLight, C.red, 18, 1.6);
  c += text(800, 752, '高风险动作默认 fail closed；人工审核只记录决定，来源 Context 必须重新校验后才能执行生效动作', { size: 18, weight: 800, fill: C.red, anchor: 'middle' });
  c += text(800, 779, '审批通过不等于业务动作已经成功', { size: 17, weight: 700, fill: C.text, anchor: 'middle' });
  return svgWrap(c, '控制与安全保障面');
}

function slide9() {
  let c = frame(9, '反馈闭环：从业务结果到受控版本发布', '【目标规范】系统可以持续改进，但改进只能以候选版本进入评估、审批和发布流程');
  c += factTag('目标规范', C.orange, C.orangeLight);
  c += text(80, 167, '反馈来源', { size: 22, weight: 800, fill: C.navy });
  const sources = [
    [80, 195, '业务指标', '转化、留存、成本、时效'],
    [80, 300, '真人反馈', '验收、评分、修正意见'],
    [80, 405, '执行信号', '失败、异常、重试与告警'],
  ];
  sources.forEach(d => c += smallNode(d[0], d[1], 270, 82, d[2], [d[3]], C.orange, C.orangeLight));

  const steps = [
    [415, 225, '1', '结果所有者', ['来源 Context', '记录真实结果', '保持事实写入权'], C.blue, C.blueLight],
    [635, 225, '2', '评估与归因', ['EvaluationRun', '识别问题来源'], C.purple, C.purpleLight],
    [855, 225, '3', '候选改进', ['Prompt / 路由', 'SOP / 能力 / 策略'], C.amber, C.amberLight],
    [1075, 225, '4', '影子评估', ['对照基线', '验证收益与风险'], C.teal, C.tealLight],
    [1295, 225, '5', '必要审批', ['PromotionDecision', '批准或拒绝'], C.red, C.redLight],
  ];
  steps.forEach((d, i) => {
    c += rect(d[0], d[1], 180, 205, C.white, d[5], 20, 2, 'filter="url(#shadow)"');
    c += circle(d[0] + 90, d[1] + 40, 24, d[5]);
    c += text(d[0] + 90, d[1] + 48, d[2], { size: 20, weight: 800, fill: C.white, anchor: 'middle' });
    c += text(d[0] + 90, d[1] + 91, d[3], { size: 20, weight: 800, fill: d[5], anchor: 'middle' });
    c += text(d[0] + 90, d[1] + 133, d[4], { size: 16, lh: 24, fill: C.muted, anchor: 'middle' });
    if (i < steps.length - 1) c += line(d[0] + 180, 327, steps[i + 1][0] - 8, 327, C.navy2, 2.4, 'arrowNavy');
  });
  sources.forEach((d, i) => c += line(350, d[1] + 41, 415, 327, C.orange, 1.8, 'arrowOrange', '6 5'));

  c += rect(420, 525, 1050, 145, C.navy, 'none', 22, 0);
  c += text(465, 567, '6  所有者发布新版本', { size: 25, weight: 800, fill: C.white });
  c += text(465, 610, ['Prompt / 专家策略 → 专家管理', '模型路由 → 模型供应商管理', 'SOP / 知识 → Wiki 管理'], { size: 17, lh: 28, fill: '#C9D8E8' });
  c += text(980, 610, ['能力定义 → 能力目录', '访问策略 → 访问控制', '发布后 → 灰度监测 · 可回滚'], { size: 17, lh: 28, fill: '#C9D8E8' });
  c += pathLine('M1385 430 L1385 525', C.green, 2.5, 'arrowGreen');
  c += pathLine('M1230 670 C1230 780 560 790 560 680', C.orange, 2.8, 'arrowOrange', '8 7');
  c += text(900, 754, 'AI 质量评估只能建议和验证，不能跨 Context 自动修改生产配置', { size: 21, weight: 800, fill: C.red, anchor: 'middle' });
  return svgWrap(c, '反馈闭环');
}

function slide10() {
  let c = frame(10, '业务场景一：运营分析——当前能力与目标接续分开表达', '当前代码可产出日报、告警和建议文本；正式提案或任务仍需由业务用例创建');
  c += factTag('当前 + 目标', C.teal, C.tealLight);
  c += pill(78, 154, 230, '当前已实现', C.blueLight, C.blue, C.blue);
  const current = [
    [70, 250, '数据接入', ['Excel 上传', 'ThinkingData 同步'], C.blue, C.blueLight],
    [325, 250, '指标事实', ['ops_daily_metric', '按日期 + 产品幂等写入'], C.teal, C.tealLight],
    [580, 250, '规则检测', ['日活 / 新增环比下降', '次留低于阈值'], C.red, C.redLight],
    [835, 250, 'AI 生成', ['运营日报', '异常告警播报'], C.purple, C.purpleLight],
    [1090, 250, '优化建议', ['结构化建议文本', '仅 AgentTaskRecord 留痕'], C.amber, C.amberLight],
  ];
  current.forEach((d, i) => {
    c += smallNode(d[0], d[1], 210, 125, d[2], d[3], d[4], d[5]);
    if (i < current.length - 1) c += line(d[0] + 210, d[1] + 62, current[i + 1][0] - 8, d[1] + 62, C.navy2, 2.4, 'arrowNavy');
  });
  c += rect(1325, 235, 220, 155, C.redLight, C.red, 18, 1.6);
  c += text(1435, 273, '当前边界', { size: 21, weight: 800, fill: C.red, anchor: 'middle' });
  c += text(1435, 311, ['不会写 ProposalCard', '不会写 TaskCard', '也不会自动启动执行'], { size: 16, lh: 26, fill: C.text, anchor: 'middle' });

  c += pill(78, 455, 230, '目标接续（待用例打通）', C.orangeLight, C.orange, C.orange);
  const target = [
    [170, 555, '管理者判断', ['只需观察：归档并监测', '需要行动：提交业务命令'], C.orange, C.orangeLight],
    [525, 555, '正式业务用例', ['创建提案', '或创建任务卡'], C.blue, C.blueLight],
    [880, 555, '任务执行与验收', ['任务 / 工作流', '产物、证据与真人验收'], C.green, C.greenLight],
    [1235, 555, '运营结果写回', ['指标 / 结果事件', '由运营分析拥有'], C.teal, C.tealLight],
  ];
  target.forEach((d, i) => {
    c += smallNode(d[0], d[1], 250, 120, d[2], d[3], d[4], d[5]);
    if (i < target.length - 1) c += line(d[0] + 250, d[1] + 60, target[i + 1][0] - 8, d[1] + 60, C.orange, 2.4, 'arrowOrange', '8 6');
  });
  c += pathLine('M1360 675 C1110 800 350 795 295 680', C.orange, 2.7, 'arrowOrange', '9 7');
  c += text(800, 763, '目标接续尚未在当前代码中自动打通：AI 报告不能直接改变提案、任务或其他业务状态', { size: 18, weight: 800, fill: C.orange, anchor: 'middle' });
  return svgWrap(c, '运营洞察闭环');
}

function slide11() {
  let c = frame(11, '业务场景二：提案管理——按当前代码状态机表达', 'AI 预研内部可执行反思和修订，但它不是一个独立业务状态；通过或驳回只能由真人写入');
  c += factTag('当前实现', C.purple, C.purpleLight);
  c += pill(78, 154, 230, '提案状态机（当前）', C.purpleLight, C.purple, C.purple);

  const nodes = [
    [60, 285, 'draft 草稿', ['创建提案后', '初始状态'], C.blue, C.blueLight],
    [285, 285, '发起 AI 预研', ['除 approved / rejected 外', '当前均可发起'], C.purple, C.purpleLight],
    [510, 285, 'researching', ['先写入“预研中”', '再调用模型'], C.teal, C.tealLight],
    [735, 285, '预研结果', ['保存 AI 评审记录', '内部反思，必要时修订'], C.purple, C.purpleLight],
    [960, 285, 'reviewed', ['预研完成', '等待真人评审'], C.amber, C.amberLight],
  ];
  nodes.forEach((d, i) => {
    c += smallNode(d[0], d[1], 185, 125, d[2], d[3], d[4], d[5]);
    if (i < nodes.length - 1) c += line(d[0] + 185, d[1] + 62, nodes[i + 1][0] - 8, d[1] + 62, C.navy2, 2.2, 'arrowNavy');
  });
  c += line(1145, 347, 1190, 347, C.navy2, 2.4, 'arrowNavy');
  c += diamond(1300, 347, 220, 135, C.redLight, C.red, '真人评审', 'approve / reject');

  c += pathLine('M1300 415 L1300 495 L1045 495', C.red, 2.5, 'arrowRed');
  c += smallNode(805, 460, 240, 110, 'rejected 已驳回', ['当前禁止再次 AI 预研', '继续需新建提案'], C.red, C.redLight);

  c += pathLine('M1410 347 L1460 347 L1460 470', C.green, 2.5, 'arrowGreen');
  c += smallNode(1335, 470, 220, 105, 'approved 已通过', ['只有该状态', '可以转换任务卡'], C.green, C.greenLight);
  c += line(1445, 575, 1445, 645, C.navy2, 2.5, 'arrowNavy');
  c += smallNode(1320, 645, 250, 95, '创建 TaskCard（仅一次）', ['重复转换会被拒绝'], C.navy2, C.grayLight);

  c += rect(85, 650, 1080, 90, C.navy, 'none', 18, 0);
  c += text(625, 686, '当前硬规则', { size: 20, weight: 800, fill: '#FFB7B7', anchor: 'middle' });
  c += text(625, 718, '真人评审只接受 reviewed；AI 无权写 approved / rejected；终态提案不能再次预研', { size: 19, weight: 800, fill: C.white, anchor: 'middle' });
  return svgWrap(c, '提案决策闭环');
}

function slide12() {
  let c = frame(12, '业务场景三：会议管理——按当前代码约束表达', '当前只强制会议状态、部分动作前置条件和“确认后才能转任务”；没有投票→纪要→决议的顺序状态机');
  c += factTag('当前实现', C.green, C.greenLight);

  c += text(75, 160, '会议状态机', { size: 22, weight: 800, fill: C.navy });
  c += smallNode(230, 145, 210, 86, 'scheduled', ['已安排'], C.blue, C.blueLight);
  c += line(440, 188, 570, 188, C.navy2, 2.4, 'arrowNavy');
  c += smallNode(570, 145, 210, 86, 'in_progress', ['进行中'], C.green, C.greenLight);
  c += line(780, 188, 910, 188, C.navy2, 2.4, 'arrowNavy');
  c += smallNode(910, 145, 210, 86, 'closed', ['已关闭 · 终态'], C.red, C.redLight);
  c += pathLine('M335 231 C335 275 1015 275 1015 231', C.red, 2, 'arrowRed', '7 6');
  c += text(675, 266, 'scheduled 也可直接关闭', { size: 15, weight: 700, fill: C.red, anchor: 'middle' });

  c += rect(70, 330, 440, 285, C.white, C.purple, 22, 2, 'filter="url(#shadow)"');
  c += text(290, 374, '必须处于进行中', { size: 25, weight: 800, fill: C.purple, anchor: 'middle' });
  c += text(290, 424, ['真人发言 / AI 专家发言', '真人投票 / AI 参考投票', '否则动作被拒绝'], { size: 19, lh: 50, weight: 700, fill: C.text, anchor: 'middle' });

  c += rect(550, 330, 440, 285, C.white, C.amber, 22, 2, 'filter="url(#shadow)"');
  c += text(770, 374, '其他动作的真实前置条件', { size: 25, weight: 800, fill: C.amber, anchor: 'middle' });
  c += text(770, 420, ['AI 生成纪要：至少已有一条发言', '创建决议草案：只校验会议存在', '投票统计：真人票和 AI 票分开'], { size: 18, lh: 52, weight: 700, fill: C.text, anchor: 'middle' });

  c += rect(1030, 330, 500, 285, C.white, C.green, 22, 2, 'filter="url(#shadow)"');
  c += text(1280, 374, '决议转任务', { size: 25, weight: 800, fill: C.green, anchor: 'middle' });
  c += smallNode(1060, 430, 150, 92, '决议草案', ['未确认'], C.amber, C.amberLight);
  c += line(1210, 476, 1240, 476, C.navy2, 2.2, 'arrowNavy');
  c += smallNode(1240, 430, 150, 92, '真人确认', ['写 confirmed_by'], C.red, C.redLight);
  c += line(1390, 476, 1420, 476, C.navy2, 2.2, 'arrowNavy');
  c += smallNode(1420, 430, 90, 92, '转任务', ['仅一次'], C.green, C.greenLight);
  c += text(1280, 570, '只有 is_confirmed=true 且尚未转换的决议可以创建 TaskCard', { size: 17, weight: 800, fill: C.green, anchor: 'middle' });

  c += rect(90, 685, 1420, 84, C.navy, 'none', 18, 0);
  c += text(800, 718, '当前没有强制“投票 → 纪要 → 决议”的固定顺序', { size: 20, weight: 800, fill: '#A9E8D5', anchor: 'middle' });
  c += text(800, 749, 'human_passed 只是统计值，不会自动确认决议；确认动作也不依赖投票是否通过', { size: 18, weight: 800, fill: C.white, anchor: 'middle' });
  return svgWrap(c, '会议决策闭环');
}

function slide13() {
  let c = frame(13, 'DDD 分类：业务场景域、基础底座域、Platform 与 Bootstrap', '【目标边界】四层运行模块不是 Bounded Context；只有拥有独立语言、生命周期和写入所有权的叶子模块才是 Context');
  c += factTag('目标边界', C.purple, C.purpleLight);
  const cols = [
    [55, 165, 285, 565, '业务场景域', C.blue, C.blueLight,
      ['提案管理', '会议管理', '运营分析'],
      ['回答：公司正在处理什么业务问题', '拥有自身业务规则、状态和事实']],
    [365, 165, 650, 565, '基础底座域（Foundation Context）', C.purple, C.purpleLight,
      ['知识：Wiki 管理 / 索引 / 检索 / 语义目录 / 组织记忆', '组织能力：组织结构 / 专家管理 / 能力目录 / 环境投影', '执行：智能体执行 / 能力执行 / 工作规划 / 工作流运行 / 任务 / 交付物', '集成数据：连接器管理 / 连接器执行 / 受治理数据查询', '沟通：助理会话 / 群消息 / 协作请求', '治理：身份 / 访问控制 / 人工审核 / 审计 / 系统配置', 'AI 运营：模型供应商 / 用量与预算 / 质量评估'],
      ['回答：多个业务场景共同依赖什么稳定业务能力', 'Foundation 是业务能力，不是纯技术设施']],
    [1040, 165, 285, 565, 'Platform', C.green, C.greenLight,
      ['数据库 / Outbox', 'HTTP / MCP 运行时', 'LLM Gateway', '缓存 / 实时通信', '对象存储', '沙箱 / 技术安全', '可观测性 / 外部集成'],
      ['回答：能力如何连接数据库、网络和供应商', 'Platform 不拥有领域事实']],
    [1350, 165, 195, 565, 'Bootstrap', C.amber, C.amberLight,
      ['应用入口', '生命周期', '依赖装配', 'Worker', 'Handler 注册'],
      ['选择实现', '组装并启动系统']],
  ];
  cols.forEach(g => {
    c += rect(g[0], g[1], g[2], g[3], C.white, g[5], 22, 2, 'filter="url(#shadow)"');
    c += rect(g[0], g[1], g[2], 70, g[6], 'none', 22, 0);
    c += rect(g[0], g[1] + 50, g[2], 20, g[6], 'none', 0, 0);
    c += text(g[0] + g[2] / 2, g[1] + 45, g[4], { size: g[2] < 220 ? 20 : 22, weight: 800, fill: g[5], anchor: 'middle' });
    const itemSize = g[2] > 600 ? 15 : 17;
    const itemLh = g[2] > 600 ? 46 : 48;
    c += text(g[0] + 24, g[1] + 115, g[7], { size: itemSize, lh: itemLh, weight: 700, fill: C.text });
    c += rect(g[0] + 20, g[1] + g[3] - 125, g[2] - 40, 100, g[6], 'none', 14, 0);
    c += text(g[0] + g[2] / 2, g[1] + g[3] - 85, g[8], { size: 14, lh: 24, weight: 700, fill: g[5], anchor: 'middle' });
  });
  c += rect(125, 770, 1350, 60, C.navy, 'none', 16, 0);
  c += text(800, 808, '任务管理与能力执行属于 Foundation Context；MCP 传输和 LLM SDK 属于 Platform', { size: 18, weight: 800, fill: C.white, anchor: 'middle' });
  return svgWrap(c, 'DDD 分类');
}

function slide14() {
  let c = frame(14, '实施状态：架构语义已定，代码按模块化单体渐进迁移', '依据规范当前状态表呈现；目标不是一次性移动文件或拆微服务，并保持现有 API、表和 durable runtime 语义');
  c += factTag('实施现状', C.green, C.greenLight);
  const states = [
    [65, 180, 280, 250, '阶段 0', '已完成', ['四层运行架构', '两大横切系统', 'DDD Context Map 分离'], C.green, C.greenLight],
    [365, 180, 280, 250, '阶段 1', '已完成首版', ['静态 import 边界测试', '仍有历史调用方时', '才保留兼容 facade'], C.blue, C.blueLight],
    [665, 180, 280, 250, '阶段 2', '进行中', ['Bootstrap / 数据库', 'Outbox / HTTP 运行时已落地'], C.purple, C.purpleLight],
    [965, 180, 280, 250, '阶段 3～4', '部分开始', ['受治理数据查询', '提案领域层 / 应用层边界'], C.amber, C.amberLight],
    [1265, 180, 280, 250, '阶段 5～8', '待增量执行', ['规划 / 运行 / 任务', '知识 / 治理 / 业务 Context'], C.red, C.redLight],
  ];
  states.forEach((s, i) => {
    c += rect(s[0], s[1], s[2], s[3], C.white, s[7], 22, 2, 'filter="url(#shadow)"');
    c += pill(s[0] + 24, s[1] + 24, 105, s[4], s[8], s[7], s[7]);
    c += text(s[0] + 24, s[1] + 100, s[5], { size: 24, weight: 800, fill: s[7] });
    c += text(s[0] + 24, s[1] + 148, s[6], { size: 17, lh: 29, weight: 600, fill: C.text });
    if (i < states.length - 1) c += line(s[0] + s[2], 305, states[i + 1][0] - 10, 305, C.navy2, 2.5, 'arrowNavy');
  });
  c += text(70, 485, '迁移约束', { size: 24, weight: 800, fill: C.navy });
  const rules = [
    [70, 525, '新实现进入对应 Context 或 Platform', C.blue, C.blueLight],
    [460, 525, '旧入口只能单向转发到新实现', C.purple, C.purpleLight],
    [850, 525, '新模块禁止反向依赖兼容入口', C.red, C.redLight],
    [1240, 525, '不因概念分层直接拆微服务', C.green, C.greenLight],
  ];
  rules.forEach(r => c += smallNode(r[0], r[1], 300, 100, r[2], ['保持行为与依赖方向可验证'], r[3], r[4]));
  c += rect(135, 700, 1330, 95, C.navy, 'none', 22, 0);
  c += text(800, 738, '最终判断标准', { size: 20, weight: 800, fill: '#9FC2E6', anchor: 'middle' });
  c += text(800, 770, '一个事实只有一个写入所有者 · 高风险动作可授权可审计 · 每个结果可回溯 · 反馈不会形成在线自修改', { size: 19, weight: 800, fill: C.white, anchor: 'middle' });
  return svgWrap(c, '实施状态');
}

const slideBuilders = [coverSlide, slide2, slide3, slide4, slide5, slide6, slide7, slide8, slide9, slide10, slide11, slide12, slide13, slide14];

async function build() {
  fs.mkdirSync(SOURCE_DIR, { recursive: true });
  fs.mkdirSync(PREVIEW_DIR, { recursive: true });

  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'AI-Youdoogo';
  pptx.company = 'AI-Youdoogo';
  pptx.subject = '企业智能体平台架构、DDD 领域边界与业务闭环';
  pptx.title = '企业智能体平台架构与业务闭环';
  pptx.lang = 'zh-CN';
  pptx.theme = {
    headFontFace: 'Microsoft YaHei',
    bodyFontFace: 'Microsoft YaHei',
    lang: 'zh-CN',
  };

  const previews = [];
  for (let i = 0; i < slideBuilders.length; i += 1) {
    const svg = slideBuilders[i]();
    const base = `slide-${String(i + 1).padStart(2, '0')}`;
    const svgPath = path.join(SOURCE_DIR, `${base}.svg`);
    const pngPath = path.join(PREVIEW_DIR, `${base}.png`);
    fs.writeFileSync(svgPath, svg, 'utf8');
    await sharp(Buffer.from(svg)).resize(1600, 900).png().toFile(pngPath);
    previews.push(pngPath);

    const slide = pptx.addSlide();
    slide.background = { color: 'F5F7FA' };
    // PowerPoint 在不同 Windows/Office 版本中会重新解析 SVG 字体，中文可能乱码。
    // PPT 内只嵌入 Sharp 已栅格化的真实 PNG；SVG 继续保留为独立设计源文件。
    slide.addImage({ path: pngPath, x: 0, y: 0, w: 13.333, h: 7.5 });
  }

  await pptx.writeFile({ fileName: PPT_PATH });

  const thumbW = 480;
  const thumbH = 270;
  const gap = 24;
  const cols = 2;
  const rows = Math.ceil(previews.length / cols);
  const montageW = cols * thumbW + (cols + 1) * gap;
  const montageH = rows * thumbH + (rows + 1) * gap;
  const comps = [];
  for (let i = 0; i < previews.length; i += 1) {
    const thumb = await sharp(previews[i]).resize(thumbW, thumbH).png().toBuffer();
    comps.push({ input: thumb, left: gap + (i % cols) * (thumbW + gap), top: gap + Math.floor(i / cols) * (thumbH + gap) });
  }
  await sharp({ create: { width: montageW, height: montageH, channels: 4, background: '#E7ECF2' } })
    .composite(comps)
    .png()
    .toFile(path.join(ROOT, '企业智能体平台架构与业务闭环-全稿预览.png'));

  console.log(`Generated ${slideBuilders.length} slides`);
  console.log(PPT_PATH);
}

build().catch(err => {
  console.error(err);
  process.exit(1);
});
