<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import ItineraryTimeline from './ItineraryTimeline.vue'
import SolutionCard from './SolutionCard.vue'

const airports = ref([])
const flights = ref([])
const loading = ref(false)
const error = ref('')
const result = ref(null)

// 航段编辑行：航班号 + RBD。航班按航段前序到达机场过滤，保证首尾相接。
const rows = ref([{ flightId: '', rbd: 'Y' }, { flightId: '', rbd: 'Y' }])

const flightById = computed(() => Object.fromEntries(flights.value.map((f) => [f.id, f])))

function availableFlights(index) {
  if (index === 0) return flights.value
  const prev = rows.value[index - 1]
  if (!prev.flightId) return flights.value
  const prevFlight = flightById.value[prev.flightId]
  if (!prevFlight) return flights.value
  return flights.value.filter((f) => f.dep_airport === prevFlight.arr_airport)
}

function addSegment() {
  rows.value.push({ flightId: '', rbd: 'Y' })
}
function removeSegment(i) {
  if (rows.value.length > 1) rows.value.splice(i, 1)
}

async function quote() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await api.quote(
      rows.value
        .filter((r) => r.flightId)
        .map((r) => ({ flight_id: Number(r.flightId), rbd: r.rbd })),
    )
  } catch (e) {
    error.value = e.payload?.error || { message: e.message }
  } finally {
    loading.value = false
  }
}

// ---- 培训案例预设（航班号在虚构数据中固定）----
const cases = [
  {
    key: 'rt-ok',
    title: '① 来回程 4 天：RT 一个价 vs 两段单程相加',
    desc: 'SHA→NRT 10/05 去、10/09 回，Y 舱。RT 净价 3200，两个 OW 相加 4200。',
    segments: [['521', 'Y'], ['524', 'Y']],
  },
  {
    key: 'min-stay',
    title: '② 跨日期最短停留失败（仅停 1 天）',
    desc: '次日即回，折返点当地日历只停 1 天 < 最短 3 天；两个 OW 也无 NRT→SHA 运价。',
    segments: [['521', 'Y'], ['522', 'Y']],
  },
  {
    key: 'tz',
    title: '③ 跨时区：UTC 已跨日、当地日历仍是同一天（0 日停留）',
    desc: 'SHA 23:00 起飞到 URC，当地次日凌晨到达，上午返回。当地日历差 0 日，UTC 裸日期差 1 日。',
    segments: [['5601', 'Y'], ['5602', 'Y']],
  },
  {
    key: 'cheap-q',
    title: '④ 单段便宜但不能组合：去 Q + 回 Y',
    desc: 'Q 特价单程 450 元很便宜，但 COMBINABILITY 要求 components_count==1，拼不进来回程。',
    segments: [['5101', 'Q'], ['5104', 'Y']],
  },
  {
    key: 'triangle',
    title: '⑤ 三角程 SHA-PEK-URC-SHA：1 停留 + 1 转机，三个 OW 组件',
    desc: '全程 Y 舱，逐段 OW 组合可成；URC 停 28h 构成一次中途停留。',
    segments: [['5107', 'Y'], ['5605', 'Y'], ['5608', 'Y']],
  },
  {
    key: 'cabin-out',
    title: '⑥ 某段舱位不可用：三角程第一段 Q 舱 0 座',
    desc: 'MU5107 的 Q 舱库存为 0，在规则判定之前就被舱位校验拦下。',
    segments: [['5107', 'Q'], ['5605', 'Q'], ['5608', 'Q']],
  },
  {
    key: 'max-stay',
    title: '⑦ 跨日期最长停留：10/05 去、10/24 回（19 天）',
    desc: '当地停留 19 天 > 最长 14 天，RT 规则 MAX_STAY 失败。',
    segments: [['521', 'Y'], ['526', 'Y']],
  },
]

async function applyCase(c) {
  rows.value = c.segments.map(() => ({ flightId: '', rbd: 'Y' }))
  await Promise.resolve()
  c.segments.forEach(([num, rbd], i) => {
    const f = flights.value.find((x) => x.number === num)
    rows.value[i] = { flightId: f ? String(f.id) : '', rbd }
  })
  await quote()
}

onMounted(async () => {
  airports.value = await api.airports()
  flights.value = await api.flights()
  await applyCase(cases[0])
})
</script>

<template>
  <div>
    <div class="panel">
      <h3>培训案例（点击直接试算）</h3>
      <div class="tabs">
        <button v-for="c in cases" :key="c.key" class="secondary" @click="applyCase(c)">
          {{ c.title }}
        </button>
      </div>
      <p v-for="c in cases" :key="'d' + c.key" class="small muted" style="margin: 2px 0">
        <b>{{ c.title }}</b> — {{ c.desc }}
      </p>
    </div>

    <div class="panel">
      <h3>手工拼行程（航段必须首尾机场相接）</h3>
      <div v-for="(row, i) in rows" :key="i" class="row" style="margin: 8px 0">
        <span class="badge info">第 {{ i + 1 }} 段</span>
        <select v-model="row.flightId">
          <option value="" disabled>选择虚构航班…</option>
          <option v-for="f in availableFlights(i)" :key="f.id" :value="String(f.id)">
            {{ f.carrier }}{{ f.number }}
            {{ f.dep_airport }}→{{ f.arr_airport }}
            | 当地 {{ f.dep_local.slice(0, 16) }}
            | 舱位 {{ f.cabins.map((c) => c.rbd + '(' + c.seats + ')').join(' ') }}
          </option>
        </select>
        <select v-model="row.rbd">
          <option v-for="rbd in ['Y', 'B', 'Q', 'J']" :key="rbd" :value="rbd">RBD {{ rbd }}</option>
        </select>
        <button class="secondary" @click="removeSegment(i)" :disabled="rows.length === 1">删除</button>
      </div>
      <div class="row" style="margin-top: 10px">
        <button class="secondary" @click="addSegment">+ 加一段</button>
        <button @click="quote" :disabled="loading">{{ loading ? '试算中…' : '试算运价组合' }}</button>
      </div>
    </div>

    <div v-if="error" class="error-box">
      <b>[{{ error.code }}]</b> {{ error.message }}
      <div v-if="error.segment_index !== undefined" class="small">
        出错航段：第 {{ error.segment_index + 1 }} 段
        <span v-if="error.flight">（{{ error.flight }}）</span>
      </div>
    </div>

    <template v-if="result && result.ok">
      <div class="panel">
        <h3>行程时间线（UTC 与机场当地日历并列，跨日看当地）</h3>
        <ItineraryTimeline :segments="result.segments" :junctions="result.junctions" />
        <div class="kv small">
          <dt>转机次数（&lt;24h）</dt><dd>{{ result.trip_summary.transfers }}</dd>
          <dt>中途停留（≥24h，不含折返点）</dt><dd>{{ result.trip_summary.stopovers }}</dd>
          <dt>折返点当地停留日</dt><dd>{{ result.trip_summary.turnaround_stay_days_local ?? '—' }}</dd>
        </div>
      </div>

      <h2>
        运价组合方案（共 {{ result.solutions.length }} 个切分/组合，
        {{ result.valid_solution_count }} 个通过规则）
      </h2>
      <p class="muted small">
        引擎会穷举「一个航段一个 OW」与「相邻去+回合成一个 RT」的所有切分，
        再逐组件套规则；不是把每段公布票价直接相加。
      </p>
      <SolutionCard
        v-for="(s, i) in result.solutions"
        :key="i"
        :solution="s"
      />
      <p class="notice">{{ result.disclaimer }}</p>
    </template>
  </div>
</template>
