#!/usr/bin/env python3
"""校验研究数据、识别重复产品、比较历史，并保存不可覆盖的报告快照。"""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit

CLAIMS = ('customer', 'problem', 'pricing', 'team', 'demand', 'acquisition',
          'wedge', 'effort', 'recurrence', 'risks', 'next_step')
ANALYSIS = ('competitors', 'mvp', 'costs', 'validation_plan')
LABELS = dict(zip(CLAIMS + ANALYSIS, (
    '客户与付费者', '问题与替代工作', '定价', '团队规模', '需求证据', '首批客户渠道',
    '差异化切口', '开发与维护', '持续付费理由', '风险与未知', '下一步验证',
    '竞品比较', 'MVP 范围', '成本假设', '验证计划与停止条件')))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def checked_date(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), '日期必须为 YYYY-MM-DD')
    return date.fromisoformat(value)


def identity(url):
    """保留路径与业务查询参数，避免把同一平台上的不同产品合并。"""
    require(nonempty(url) and not re.search(r'[\s<>\\]', url), 'URL 格式无效')
    parsed = urlsplit(url)
    require(parsed.scheme in ('http', 'https') and parsed.hostname, '仅接受完整 HTTP(S) URL')
    require(parsed.username is None and parsed.password is None, 'URL 不得包含凭据')
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    sensitive = {'token', 'access_token', 'api_key', 'apikey', 'key', 'password', 'secret', 'signature'}
    require(not any(k.lower() in sensitive or k.lower().startswith('x-amz-') for k, _ in pairs),
            'URL 不得包含敏感查询参数')
    host = parsed.hostname.lower().removeprefix('www.')
    port = parsed.port
    if port and not ((parsed.scheme == 'http' and port == 80) or (parsed.scheme == 'https' and port == 443)):
        host += ':' + str(port)
    query = urlencode(sorted((k, v) for k, v in pairs
                             if not k.lower().startswith('utm_') and k.lower() not in {'gclid', 'fbclid'}))
    return host + parsed.path.rstrip('/') + ('?' + query if query else '')


def validate(data):
    """验证结构和可机械检查的证据约束；来源真实性仍由研究者核验。"""
    require(isinstance(data, dict) and type(data.get('schema_version')) is int
            and data['schema_version'] == 1, 'schema_version 必须为 1')
    require(data.get('mode') in ('discovery', 'deep-dive', 'smoke-test'), 'mode 无效')
    observed = checked_date(data.get('observed_on'))
    require(nonempty(data.get('scope')), '缺少 scope')
    limit = data.get('shortlist_limit')
    require(type(limit) is int and limit >= 0, 'shortlist_limit 必须为非负整数')
    for key in ('queries', 'limitations'):
        require(isinstance(data.get(key), list) and all(nonempty(v) for v in data[key]), key + ' 必须为字符串数组')
    require(isinstance(data.get('sources'), list), '缺少 sources 数组')
    sources = {}
    for source in data['sources']:
        require(isinstance(source, dict), 'source 必须为对象')
        sid = source.get('id')
        require(nonempty(sid) and sid not in sources, '来源 id 缺失或重复')
        identity(source.get('url'))
        require(nonempty(source.get('title')), '来源缺少 title')
        require(source.get('kind') in ('official', 'founder', 'customer', 'directory', 'third_party'), '来源 kind 无效')
        require(source.get('status') in ('ok', 'blocked', 'error'), '来源 status 无效')
        require(checked_date(source.get('accessed_on')) <= observed, '来源访问日期晚于研究日期')
        require('published_on' in source, '来源缺少 published_on，未知填 null')
        if source['published_on'] is not None:
            require(checked_date(source['published_on']) <= checked_date(source['accessed_on']), '发布日期晚于访问日期')
        sources[sid] = source

    def references(refs):
        require(isinstance(refs, list) and all(nonempty(s) for s in refs), 'source_ids 必须为字符串数组')
        for sid in refs:
            require(sid in sources and sources[sid]['status'] == 'ok', '引用不存在或不可访问的来源: ' + sid)

    def claim_check(claim):
        require(isinstance(claim, dict), 'claim 必须为对象')
        require(claim.get('basis') in ('fact', 'inference', 'unknown'), 'claim basis 无效')
        references(claim.get('source_ids'))
        if claim['basis'] == 'unknown':
            require('text' in claim and claim['text'] is None and not claim['source_ids'], '未知值必须为 null，不能附带事实或引文')
        else:
            require(nonempty(claim.get('text')), '事实或推断必须有 text')
            if claim['basis'] == 'fact':
                require(claim['source_ids'], '事实必须有已访问来源')

    require(isinstance(data.get('products'), list), '缺少 products 数组')
    identities = set()
    shortlisted = 0
    for product in data['products']:
        require(isinstance(product, dict), 'product 必须为对象')
        require(nonempty(product.get('name')), '产品缺少 name')
        pid = identity(product.get('website'))
        require(pid not in identities, '重复产品，请人工合并证据并解决冲突: ' + pid)
        identities.add(pid)
        require(product.get('decision') in ('shortlist', 'watch', 'exclude'), 'decision 无效')
        require(nonempty(product.get('reason')), '产品缺少筛选理由')
        require(product.get('evidence_level') in ('commercial', 'demand', 'insufficient'), 'evidence_level 无效')
        claims = product.get('claims')
        require(isinstance(claims, dict) and set(claims) == set(CLAIMS), 'claims 字段不完整或含未知字段')
        for claim in claims.values():
            claim_check(claim)
        revenue = product.get('revenue')
        require(isinstance(revenue, dict), '缺少 revenue 对象')
        require(revenue.get('status') in ('unknown', 'founder_reported', 'verified_record'), 'revenue status 无效')
        references(revenue.get('source_ids'))
        if revenue['status'] == 'unknown':
            require('text' in revenue and 'as_of' in revenue and revenue['text'] is None
                    and revenue['as_of'] is None and not revenue['source_ids'], '未知收入必须为空且不绑定收入来源')
        else:
            require(nonempty(revenue.get('text')) and nonempty(revenue.get('as_of'))
                    and revenue['source_ids'], '收入必须有指标/单位、所属时期和来源')
        if product['decision'] == 'shortlist':
            shortlisted += 1
            require(product['evidence_level'] != 'insufficient' and claims['demand']['source_ids'],
                    '入选必须有需求证据，不能仅凭报价或想法')
        if data['mode'] == 'deep-dive' or 'analysis' in product:
            analysis = product.get('analysis')
            require(isinstance(analysis, dict) and set(analysis) == set(ANALYSIS), '缺少完整 analysis')
            for value in analysis.values():
                claim_check(value)
    require(shortlisted <= limit, '入选数超出 shortlist_limit')
    return data


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def comparison_fields(product, sources):
    """来源 id 可以变；比较实际内容和来源 URL，不把查询时间当业务变化。"""
    def normalized(value):
        return {**value, 'source_ids': sorted({sources[sid]['url'] for sid in value['source_ids']})}
    result = {k: product[k] for k in ('name', 'decision', 'reason', 'evidence_level')}
    result['revenue'] = normalized(product['revenue'])
    for group in ('claims', 'analysis'):
        for key, value in product.get(group, {}).items():
            result[group + '.' + key] = normalized(value)
    return result


def compare(current, history):
    """使用每个产品最近一次历史记录；未复查不等于停运或淘汰。"""
    previous = {}
    for snapshot in sorted(history, key=lambda item: item['observed_on']):
        require(snapshot['observed_on'] <= current['observed_on'], '历史快照晚于本次研究日期')
        sources = {s['id']: s for s in snapshot['sources']}
        for product in snapshot['products']:
            previous[identity(product['website'])] = comparison_fields(product, sources)
    result = {'new': [], 'returning': [], 'not_rechecked': []}
    current_ids = set()
    sources = {s['id']: s for s in current['sources']}
    for product in current['products']:
        pid = identity(product['website'])
        current_ids.add(pid)
        if pid not in previous:
            result['new'].append(pid)
        else:
            fields = comparison_fields(product, sources)
            changed = sorted(k for k in fields.keys() | previous[pid].keys()
                             if fields.get(k) != previous[pid].get(k))
            result['returning'].append({'product': pid, 'changed_fields': changed})
    result['not_rechecked'] = sorted(previous.keys() - current_ids)
    return result


def clean(text):
    """研究文本按纯文本呈现，链接只由已校验的来源字段生成。"""
    value = str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]#|])', r'\\\1', value).replace('\n', ' ')


def render(data, changes):
    sources = {s['id']: s for s in data['sources']}

    def links(refs):
        return ' '.join('[' + clean(sources[s]['title']) + '](<' + sources[s]['url'] + '>)' for s in refs)

    def describe(value):
        if value['basis'] == 'unknown':
            return '未知'
        return {'fact': '有来源陈述', 'inference': '推断'}[value['basis']] + '：' + clean(value['text']) + ' ' + links(value['source_ids'])

    lines = ['# 微型 SaaS 机会报告', '',
             f"日期：{data['observed_on']}；模式：{data['mode']}", '', clean(data['scope']), '',
             '证据等级由研究者判读；结构校验不能证明来源真实或判断正确。', '',
             f"候选 {len(data['products'])}；入选 {sum(p['decision'] == 'shortlist' for p in data['products'])}；"
             f"历史新增 {len(changes['new'])}；再次研究 {len(changes['returning'])}。", '',
             '## 范围与缺口', '']
    lines += ['- ' + clean(value) for value in data['limitations']] or ['未记录额外缺口。']
    for product in data['products']:
        lines += ['', '## ' + clean(product['name']), '',
                  '[官网](<' + product['website'] + '>)', '',
                  '结论：' + clean(product['decision']) + '；证据：' + clean(product['evidence_level']), '',
                  clean(product['reason']), '']
        for key, claim in product['claims'].items():
            lines += ['- **' + LABELS[key] + '**：' + describe(claim)]
        revenue = product['revenue']
        lines += ['', '收入：' + clean(revenue['status']) + '；' + clean(revenue['text'] or '未知')
                  + '；所属时期：' + clean(revenue['as_of'] or '未知') + ' ' + links(revenue['source_ids'])]
        for key, claim in product.get('analysis', {}).items():
            lines += ['', '### ' + LABELS[key], '', describe(claim)]
    lines += ['', '## 历史变化', '']
    lines += ['- 新增：' + clean(pid) for pid in changes['new']]
    lines += ['- 再次研究：' + clean(item['product']) + '；变化字段：'
              + clean(', '.join(item['changed_fields']) or '无') for item in changes['returning']]
    lines += ['- 本次未复查（不代表停运）：' + clean(pid) for pid in changes['not_rechecked']]
    lines += ['', '## 搜索记录', ''] + ['- ' + clean(query) for query in data['queries']]
    lines += ['', '## 来源记录', '']
    for s in data['sources']:
        lines += ['- [' + clean(s['title']) + '](<' + s['url'] + '>) — ' + clean(s['kind'])
                  + ' / ' + clean(s['status']) + '；访问 ' + s['accessed_on']
                  + '；发布 ' + (s['published_on'] or '未知')]
    return '\n'.join(line.rstrip() for line in lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'save'))
    parser.add_argument('input', type=Path, help='按 references/evaluation.md 契约生成的研究 JSON')
    parser.add_argument('--output', type=Path, help='save 必需；必须是不存在的新目录')
    parser.add_argument('--history', type=Path, action='append', default=[], help='可重复；历史 results.json，按日期及参数顺序比较')
    args = parser.parse_args()
    try:
        data = load(args.input)
        history = [load(path) for path in args.history]
        changes = compare(data, history)
        if args.command == 'save':
            require(args.output is not None, 'save 需要 --output')
            outputs = {
                'results.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                'changes.json': json.dumps(changes, ensure_ascii=False, indent=2) + '\n',
                'report.md': render(data, changes),
            }
            # 所有输入完成校验后才创建目录；独占创建避免覆盖旧研究。
            args.output.mkdir(parents=True, exist_ok=False)
            for name, content in outputs.items():
                (args.output / name).write_text(content, encoding='utf-8')
        print(json.dumps({'valid': True, 'products': len(data['products']), 'changes': changes}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('错误: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
