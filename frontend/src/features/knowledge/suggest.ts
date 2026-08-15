/** 新建任务时的知识推荐：把标题+描述拼成检索词（B1.5，只读推荐，不改任务）。 */

/** 拼标题+描述为检索词；去空白、太短(<2)返回 null（不值得检索）。 */
export function buildSuggestQuery(title?: string | null, description?: string | null): string | null {
  const query = [title ?? '', description ?? ''].join(' ').trim()
  return query.length >= 2 ? query : null
}
