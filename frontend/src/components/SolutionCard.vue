<script setup>
import { computed } from 'vue'
import { cny } from '../api'
import RuleHit from './RuleHit.vue'

const props = defineProps({ solution: Object })

const failedHits = computed(() => (props.solution.rule_hits || []).filter((h) => !h.passed))
const passedHits = computed(() => (props.solution.rule_hits || []).filter((h) => h.passed))
</script>

<template>
  <div
    class="solution"
    :class="solution.valid ? ['valid', { cheapest: solution.cheapest_valid }] : 'invalid'"
  >
    <div class="row" style="justify-content: space-between">
      <div>
        <span class="badge" :class="solution.valid ? 'ok' : 'bad'">
          {{ solution.valid ? '可用组合' : '不可用组合' }}
        </span>
        <span v-if="solution.cheapest_valid" class="badge ok" style="margin-left: 6px">
          ✓ 最低可用价
        </span>
      </div>
      <div v-if="solution.valid" style="text-align: right">
        <div class="muted small">运价净额 + 税合计</div>
        <div class="money-big">{{ cny(solution.total_amount) }}</div>
      </div>
    </div>

    <div v-if="solution.message" class="error-box small" style="margin-top: 10px">
      {{ solution.message }}
    </div>

    <template v-if="solution.components">
      <h3 style="margin-top: 12px">运价组件（一个组件可覆盖多段，不是逐段相加）</h3>
      <table>
        <thead>
          <tr>
            <th>运价</th><th>方向</th><th>覆盖航段</th><th>订座舱</th><th>净额</th><th>规则版本</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(c, i) in solution.components" :key="i">
            <td><b>{{ c.fare_code }}</b><br /><span class="muted small">{{ c.carrier }} {{ c.origin }}-{{ c.destination }}</span></td>
            <td>{{ c.direction === 'RT' ? '来回程（一个价覆盖去+回）' : '单程' }}</td>
            <td>#{{ c.segments.map((x) => x + 1).join('、#') }}</td>
            <td>{{ c.rbd }}</td>
            <td class="mono">{{ cny(c.amount) }}</td>
            <td>
              <span v-for="b in solution.blocks" :key="b.fare_id">
                <span v-if="b.fare_id === c.fare_id" class="badge info">v-id {{ b.rule_version_id }}</span>
              </span>
            </td>
          </tr>
          <tr>
            <td colspan="4" style="text-align: right" class="muted">净额合计（组件之和）</td>
            <td class="mono"><b>{{ cny(solution.base_amount) }}</b></td>
            <td></td>
          </tr>
        </tbody>
      </table>

      <div class="grid2" style="margin-top: 10px">
        <div>
          <h3>税项（逐段计收，分别列示，不揉进票价）</h3>
          <table>
            <tbody>
              <tr v-for="t in solution.taxes.items" :key="t.code">
                <td><b>{{ t.code }}</b><br /><span class="muted small">{{ t.name }}</span></td>
                <td class="small muted">
                  <span v-for="(p, k) in t.per_segment" :key="k">
                    #{{ p.segment_index + 1 }} {{ cny(p.amount) }}<br v-if="k < t.per_segment.length - 1" />
                  </span>
                </td>
                <td class="mono">{{ cny(t.total) }}</td>
              </tr>
              <tr>
                <td colspan="2" style="text-align: right" class="muted">税合计</td>
                <td class="mono"><b>{{ cny(solution.taxes.total) }}</b></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div>
          <h3>失败规则（{{ failedHits.length }}）</h3>
          <div v-if="!failedHits.length" class="notice small">全部规则通过。</div>
          <RuleHit v-for="(h, i) in failedHits" :key="'f' + i" :hit="h" />
          <details>
            <summary>查看通过的规则（{{ passedHits.length }}）</summary>
            <RuleHit v-for="(h, i) in passedHits" :key="'p' + i" :hit="h" />
          </details>
        </div>
      </div>
    </template>
  </div>
</template>
