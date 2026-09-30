<script setup>
import { computed } from 'vue'

const props = defineProps({
  hits: { type: Array, default: () => [] },
  partition: { type: String, default: '' },
})

const rows = computed(() =>
  props.hits
    .filter((h) => h.partition_key === props.partition)
    .map((h) => ({ ...h, _key: `${h.fare_code}-${h.rule_code}-${h.segment_indexes.join('.')}` })))

const categoryColor = {
  AVAILABILITY: 'fail',
  DATE_CHANGE: 'warn',
  COMBINATION: 'warn',
  ITINERARY: 'fail',
}
</script>

<template>
  <details>
    <summary>
      规则命中明细（{{ rows.length }} 条，含表达式与取值现场，可回溯版本）
    </summary>
    <table>
      <thead>
        <tr>
          <th>结果</th><th>运价/航段</th><th>规则</th><th>说明</th>
          <th>表达式现场</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="h in rows" :key="h._key">
          <td>
            <span
              class="badge"
              :class="h.result === 'PASS' ? 'ok' : 'fail'"
            >{{ h.result === 'PASS' ? '通过' : '未通过' }}</span>
            <br v-if="h.chosen" />
            <span v-if="h.chosen" class="badge chosen small">中选</span>
          </td>
          <td>
            <code class="mono">{{ h.fare_code || '—' }}</code><br />
            <span class="muted small">
              {{ h.segment_indexes.map(i => '段' + (i + 1)).join('、') }}
            </span>
          </td>
          <td>
            <code class="mono">{{ h.rule_code }}</code>
            <div>
              <span
                class="badge neutral small"
                :class="categoryColor[h.rule_category] || 'neutral'"
              >{{ h.rule_category }}</span>
            </div>
            <div class="muted small">版本 {{ h.rule_version }}</div>
          </td>
          <td>{{ h.message }}</td>
          <td style="min-width:260px">
            <div v-if="h.expression" class="expr">{{ h.expression }}</div>
            <div class="ctx-grid">
              <span v-for="(v, k) in h.context" :key="k">
                <b>{{ k }}</b>:
                {{ Array.isArray(v) ? '[' + v.join(', ') + ']' : v }}
              </span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </details>
</template>
