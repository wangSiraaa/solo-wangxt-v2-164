<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import ItineraryView from '../components/ItineraryView.vue'
import CandidateCard from '../components/CandidateCard.vue'

const props = defineProps({
  versions: { type: Array, default: () => [] },
})

const flights = ref([])
const loading = ref(false)
const error = ref('')
const result = ref(null)
const issuedTicket = ref(null)
const bookingDate = ref('2026-09-25')
const selectedVersion = ref('')

// 选中的航段 [{flight_id, booking_class}]
const picked = ref([])

// 教学场景（flight_no 序列 + 舱位 + 规则版本）
const scenarios = [
  {
    key: 'A',
    label: 'A · 联程运价 700 元覆盖两段（对比逐段相加 780/951）',
    legs: [['CA1201', 'M'], ['MU2317', 'M']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'A2',
    label: 'A2 · 单段各 300/320 更便宜，但禁止联程组合',
    legs: [['CA1209', 'Q'], ['MU2325', 'Q']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'B-v2',
    label: 'B · 跨本地午夜转机（v2 新规则拒绝，红眼中转）',
    legs: [['CA1211', 'M'], ['MU2319', 'M']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'B-v1',
    label: "B' · 同一跨午夜行程用 v1 试算（旧版放行，演示版本演进）",
    legs: [['CA1211', 'M'], ['MU2319', 'M']],
    version: 'RULE-2026-Q4-v1',
  },
  {
    key: 'C',
    label: 'C · 某段 Q 舱余座 0 / 已关闭',
    legs: [['CA1211', 'Q'], ['MU2319', 'Q']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'D',
    label: 'D · 西安停留 25.5 小时（≥24h 为停留，仍允许 1 次）',
    legs: [['CA1201', 'H'], ['MU2331', 'H']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'RT-OK',
    label: 'RT · 往返停留 5 天含周六过夜（最短/最长停留）',
    legs: [['CA1201', 'M'], ['MU2317', 'M'], ['MU2308', 'L'], ['CA1208', 'L']],
    version: 'RULE-2026-Q4-v2',
  },
  {
    key: 'RT-SHORT',
    label: "RT' · 仅停留 2 天且无周六过夜（最短停留+周六规则拒绝）",
    legs: [['CA1201', 'M'], ['MU2317', 'M'], ['MU2306', 'L'], ['CA1206', 'L']],
    version: 'RULE-2026-Q4-v2',
  },
]

onMounted(async () => {
  flights.value = await api.flights()
  loadScenario(scenarios[0])
})

function flightByNo(no) {
  return flights.value.find((f) => `${f.carrier}${f.flight_no}` === no)
}

function loadScenario(s) {
  selectedVersion.value = s.version
  result.value = null
  error.value = ''
  issuedTicket.value = null
  picked.value = s.legs.map(([no, bc]) => {
    const f = flightByNo(no)
    return {
      flight_id: f?.id ?? null,
      flight_no: no,
      booking_class: bc,
    }
  })
}

const cabinMap = computed(() => {
  const m = {}
  for (const f of flights.value) {
    m[f.id] = f.cabins
  }
  return m
})

function cabinOptions(flightId) {
  return cabinMap.value[flightId] || []
}

function addSegment() {
  picked.value.push({ flight_id: flights.value[0]?.id, booking_class: 'Y' })
}

async function runPrice() {
  loading.value = true
  error.value = ''
  result.value = null
  issuedTicket.value = null
  try {
    result.value = await api.price({
      flight_ids: picked.value.map((p) => p.flight_id),
      booking_classes: picked.value.map((p) => p.booking_class),
      booking_date: bookingDate.value || null,
      rule_version: selectedVersion.value || null,
    })
  } catch (e) {
    error.value = `试算失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function issueTicket() {
  try {
    issuedTicket.value = await api.issue(result.value.id)
  } catch (e) {
    error.value = `出票(培训)失败：${e.message}`
  }
}

const ok = computed(() => result.value?.status === 'OK')

// JSON 反序列化后 chosen 与候选不是同一对象引用，按结构特征比对
function sig(c) {
  return `${c.partition.join(',')}::` +
    (c.components || []).map((x) => x.fare_code).join(',')
}
function isChosen(c) {
  const chosen = result.value?.trace?.chosen
  return !!chosen && sig(chosen) === sig(c)
}
</script>

<template>
  <div class="grid">
    <div class="card">
      <h2>选择教学场景或自行编排航段</h2>
      <div class="scenario-chips">
        <button
          v-for="s in scenarios"
          :key="s.key"
          class="chip"
          @click="loadScenario(s)"
        >{{ s.label }}</button>
      </div>

      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:end">
        <label class="small muted">
          规则版本
          <select v-model="selectedVersion">
            <option value="">（最新生效）</option>
            <option v-for="v in versions" :key="v.version" :value="v.version">
              {{ v.version }} — {{ v.description }}
            </option>
          </select>
        </label>
        <label class="small muted">
          模拟购票日期
          <input type="date" v-model="bookingDate" />
        </label>
        <button class="btn" :disabled="loading" @click="runPrice">
          {{ loading ? '试算中…' : '执行运价组合试算' }}
        </button>
        <button class="btn secondary" @click="addSegment">＋加一段</button>
      </div>

      <div style="margin-top:12px">
        <div v-for="(p, i) in picked" :key="i" class="seg-row">
          <strong>段{{ i + 1 }}</strong>
          <select v-model.number="p.flight_id">
            <option
              v-for="f in flights"
              :key="f.id"
              :value="f.id"
            >{{ f.carrier }}{{ f.flight_no }}
              {{ f.dep_airport }}-{{ f.arr_airport }}
              {{ f.dep_local }}</option>
          </select>
          <select v-model="p.booking_class">
            <option
              v-for="c in cabinOptions(p.flight_id)"
              :key="c.booking_class"
              :value="c.booking_class"
              :disabled="!c.available"
            >{{ c.booking_class }}舱 · {{ c.seats }}座 · {{ c.status }}</option>
          </select>
          <button
            class="btn secondary"
            style="padding:4px 10px"
            @click="picked.splice(i, 1)"
          >删</button>
        </div>
      </div>
    </div>

    <p v-if="error" class="banner fail">{{ error }}</p>

    <template v-if="result">
      <div class="card">
        <h2>
          行程时间轴（UTC 与机场当地时间并列）
          <span class="badge neutral">规则版本 {{ result.rule_version }}</span>
          <span class="badge" :class="ok ? 'ok' : 'fail'">
            {{ result.status_label }}
          </span>
        </h2>
        <ItineraryView
          :segments="result.trace.segments"
          :transits="result.trace.transits"
        />
        <p v-if="result.trace.errors?.length" class="banner fail">
          {{ result.trace.errors.join('；') }}
        </p>
      </div>

      <div v-if="ok" class="card">
        <h2>中选报价：运价组件 + 分列税项</h2>
        <div class="totals">
          <div class="t muted">运价基数（组件之和，非逐段票价相加）
            <b class="money">¥{{ result.base_fare }}</b></div>
          <div class="t muted">税项合计
            <b class="money">¥{{ result.tax_total }}</b></div>
          <div class="t">含税总价
            <b class="money" style="font-size:24px">¥{{ result.total }}</b></div>
        </div>
        <table>
          <thead>
            <tr><th>组件</th><th>运价</th><th>覆盖航段</th>
              <th>基数</th><th>税</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in result.components" :key="c.seq">
              <td>{{ c.seq + 1 }}</td>
              <td><code class="mono">{{ c.fare_code }}</code></td>
              <td>{{ c.segment_indexes.map(i => '段' + (i + 1)).join('、') }}</td>
              <td class="money">¥{{ c.base_fare }}</td>
              <td class="money">¥{{ c.tax_total }}</td>
            </tr>
          </tbody>
        </table>
        <h3>税项分别列示</h3>
        <table>
          <tbody>
            <tr v-for="(t, i) in result.taxes" :key="i">
              <td><code class="mono">{{ t.code }}</code></td>
              <td>{{ t.name }}</td>
              <td>组件{{ t.component_seq + 1 }}</td>
              <td class="money">¥{{ t.amount }}</td>
            </tr>
          </tbody>
        </table>

        <div style="margin-top:12px;display:flex;gap:10px;align-items:center">
          <button class="btn secondary" @click="issueTicket">
            生成 TRN- 培训票（不产生真实购票指令）
          </button>
          <span v-if="issuedTicket" class="badge ok">
            已生成培训票 {{ issuedTicket.ticket_no }}，可在「培训票与改签」页继续演练
          </span>
        </div>
      </div>

      <div v-else class="card">
        <h2>无可用组合</h2>
        <p class="banner fail">{{ result.failure_reason }}</p>
        <p class="muted small">
          注意：即便逐段单买总价更低（见候选卡片中的价格），只要联程组合被禁、
          跨日期变更规则未通过或舱位不可用，就不构成可出票运价组合。
        </p>
      </div>

      <div class="card">
        <h2>
          全部候选组合（{{ result.trace.candidates.length }} 种切分）
          与规则命中轨迹
        </h2>
        <p class="muted small">
          引擎枚举 N 段的全部 {{ '2' }}<sup>max(N-1,0)</sup>
          种连续切分；展开任一卡片可查看每条表达式规则的
          <b>通过/未通过</b>、求值时的变量取值与规则版本。
          报价单编号 <code class="mono">#{{ result.id }}</code>，
          可据此追溯入库的 RuleHit 记录。
        </p>
        <CandidateCard
          v-for="(c, i) in result.trace.candidates"
          :key="i"
          :candidate="c"
          :chosen="isChosen(c)"
          :hits="result.hits"
        />
      </div>
    </template>
  </div>
</template>
