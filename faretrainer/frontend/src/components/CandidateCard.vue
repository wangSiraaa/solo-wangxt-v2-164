<script setup>
import RuleHits from './RuleHits.vue'

defineProps({
  candidate: { type: Object, required: true },
  chosen: { type: Boolean, default: false },
  hits: { type: Array, default: () => [] },
})
</script>

<template>
  <div
    class="candidate"
    :class="chosen ? 'chosen' : (candidate.passed ? '' : 'rejected')"
  >
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span class="partition-desc">
        切分 [{{ candidate.partition.join(' + ') }}]
      </span>
      <span>
        <span v-if="chosen" class="badge chosen">✓ 中选（含税最低合法组合）</span>
        <span v-else-if="candidate.passed" class="badge ok">合法但更贵</span>
        <span v-else class="badge fail">淘汰</span>
      </span>
    </div>

    <div v-if="candidate.components && candidate.components.length">
      <table style="margin-top:8px">
        <thead>
          <tr>
            <th>组件</th><th>运价</th><th>覆盖航段</th><th>运价基数</th>
            <th>组件税额</th><th>允许联程</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in candidate.components" :key="c.seq">
            <td>{{ c.seq + 1 }}</td>
            <td><code class="mono">{{ c.fare_code }}</code></td>
            <td>{{ c.segment_indexes.map(i => '段' + (i + 1)).join('、') }}</td>
            <td class="money">¥{{ c.base_fare }}</td>
            <td class="money">¥{{ c.tax_total }}</td>
            <td>
              <span class="badge" :class="c.end_on_end_allowed ? 'ok' : 'fail'">
                {{ c.end_on_end_allowed ? '允许' : '禁止 end-on-end' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <details>
        <summary>税项分别列示（不并入运价）</summary>
        <table>
          <thead><tr><th>组件</th><th>税码</th><th>税名</th><th>金额</th></tr></thead>
          <tbody>
            <tr v-for="(t, i) in candidate.taxes" :key="i">
              <td>{{ t.component_seq + 1 }}</td>
              <td><code class="mono">{{ t.code }}</code></td>
              <td>{{ t.name }}</td>
              <td class="money">¥{{ t.amount }}</td>
            </tr>
          </tbody>
        </table>
      </details>

      <div class="totals">
        <div class="t muted">运价基数<b class="money">¥{{ candidate.base_fare }}</b></div>
        <div class="t muted">税额合计<b class="money">¥{{ candidate.tax_total }}</b></div>
        <div class="t">含税总价<b class="money">¥{{ candidate.total }}</b></div>
      </div>
    </div>

    <p v-if="candidate.rejected_reason" class="banner fail" style="margin:8px 0">
      {{ candidate.rejected_reason }}
    </p>
    <p v-else-if="candidate.reason" class="banner fail" style="margin:8px 0">
      {{ candidate.reason }}
    </p>

    <RuleHits
      :hits="hits"
      :partition="String(candidate.partition)"
    />
  </div>
</template>
