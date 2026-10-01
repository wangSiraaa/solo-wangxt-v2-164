<script setup>
import { computed, ref } from 'vue'
import { api, cny } from '../api'
import ItineraryTimeline from './ItineraryTimeline.vue'
import RuleHit from './RuleHit.vue'

const pnr = ref('TST101')
const changes = ref([{ coupon_seq: 2, newNumber: '524B', new_rbd: 'Y' }])
const result = ref(null)
const error = ref('')
const loading = ref(false)
const flights = ref([])

const pnrPresets = [
  { pnr: 'TST101', desc: '正常客票 SHA⇄NRT（两张票联 OPEN）' },
  { pnr: 'TST202', desc: '第 1 张票联已乘机 USED（改签应被拦）' },
  { pnr: 'TST303', desc: '出票时冻结 v1 规则，现行 v2（手续费已上调）' },
]

const changePresets = [
  {
    label: '回程改 10/12（同舱、起飞前 11 天）',
    rows: [{ coupon_seq: 2, newNumber: '524B', new_rbd: 'Y' }],
  },
  {
    label: '回程改 10/24（停留 19 天，违反最长停留）',
    rows: [{ coupon_seq: 2, newNumber: '526', new_rbd: 'Y' }],
  },
]

async function ensureFlights() {
  if (!flights.value.length) flights.value = await api.flights()
}

function applyChangePreset(p) {
  changes.value = p.rows.map((r) => ({ ...r }))
}

function flightIdByNumber(num) {
  return flights.value.find((f) => f.number === num)?.id
}

async function submit() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    await ensureFlights()
    const payload = changes.value.map((c) => ({
      coupon_seq: Number(c.coupon_seq),
      new_flight_id: Number(flightIdByNumber(c.newNumber)),
      new_rbd: c.new_rbd,
    }))
    result.value = await api.rebook(pnr.value, payload)
  } catch (e) {
    error.value = e.payload?.error?.message || e.message
  } finally {
    loading.value = false
  }
}

const checks = computed(() => result.value?.checks || [])
const fee = computed(() => result.value?.fee)
const cmp = computed(() => result.value?.comparison)
const requote = computed(() => result.value?.requote)
</script>

<template>
  <div>
    <div class="panel">
      <h3>改签试算顺序（教学口径）</h3>
      <ol class="small muted" style="margin: 6px 0 0 18px; padding: 0">
        <li>先逐张检查剩余<b>票联状态</b>：必须为 OPEN，USED/EXCHANGED/REFUNDED 直接终止，不进入计价；</li>
        <li>再检查新行程的时间衔接与<b>舱位可用</b>，并按运价组件重新跑规则；</li>
        <li>最后才算<b>价差 + 手续费</b>，税项按新行程逐段重算、分别列示。</li>
      </ol>
    </div>

    <div class="panel">
      <div class="row">
        <label>虚构客票 PNR：
          <select v-model="pnr">
            <option v-for="p in pnrPresets" :key="p.pnr" :value="p.pnr">{{ p.pnr }}（{{ p.desc }}）</option>
          </select>
        </label>
      </div>
      <p class="small muted" style="margin-top: 6px">
        <span v-for="p in pnrPresets" :key="p.pnr">
          <b>{{ p.pnr }}</b>：{{ p.desc }}<br />
        </span>
      </p>

      <h3 style="margin-top: 14px">变更票联</h3>
      <div v-for="(c, i) in changes" :key="i" class="row" style="margin: 8px 0">
        <label class="small">票联序号
          <input v-model.number="c.coupon_seq" type="number" min="1" max="4" style="width: 80px" />
        </label>
        <label class="small">改到航班
          <input v-model="c.newNumber" placeholder="如 524B" style="width: 110px" />
        </label>
        <label class="small">新舱位
          <select v-model="c.new_rbd">
            <option v-for="r in ['Y', 'B', 'Q', 'J']" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>
      </div>
      <div class="row">
        <button v-for="p in changePresets" :key="p.label" class="secondary" @click="applyChangePreset(p)">
          {{ p.label }}
        </button>
      </div>
      <div class="row end" style="margin-top: 10px">
        <button @click="submit" :disabled="loading">{{ loading ? '试算中…' : '试算改签' }}</button>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <template v-if="result">
      <div class="panel">
        <div class="row" style="justify-content: space-between">
          <h2 style="margin: 0">
            结果：
            <span :class="result.eligible ? 'badge ok' : 'badge bad'">
              {{ result.eligible ? '可以换开（试算）' : '不可改签' }}
            </span>
          </h2>
          <span v-if="result.snapshot_rule_version_id" class="small muted">
            出票快照规则版本 #{{ result.snapshot_rule_version_id }}
            （{{ result.snapshot_at }} 冻结）
          </span>
        </div>

        <h3 style="margin-top: 14px">① 票联状态检查 → ② 行程/规则 → ③ 费用</h3>
        <table>
          <tbody>
            <tr v-for="(c, i) in checks" :key="i">
              <td style="width: 130px">
                <span class="badge" :class="c.passed ? 'ok' : 'bad'">
                  {{ c.passed ? '通过' : '未通过' }}
                </span>
              </td>
              <td><b>{{ c.stage }}</b>
                <span v-if="c.coupon_seq" class="muted small"> · 票联 #{{ c.coupon_seq }}
                  <span v-if="c.status">（{{ c.status }}）</span>
                </span>
              </td>
              <td class="small">{{ c.message }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="result.eligible">
        <div class="grid2">
          <div class="panel">
            <h3>② 新行程重算（含未改动但同组件的票联）</h3>
            <ItineraryTimeline
              v-if="requote"
              :segments="requote.segments"
              :junctions="requote.junctions"
            />
            <div class="kv small">
              <dt>同舱等</dt><dd>{{ result.change_context.same_cabin ? '是' : '否' }}</dd>
              <dt>距新航班起飞</dt><dd>{{ result.change_context.days_before_departure }} 天</dd>
            </div>
          </div>

          <div class="panel">
            <h3>③ 手续费规则（按现行版本判定，可追溯）</h3>
            <div v-if="fee" class="small">
              <p>
                原运价当前规则版本：
                <b>v{{ fee.applied_version_number }}</b>
                <span class="muted">{{ fee.applied_version_note }}（#{{ fee.applied_version_id }}）</span>
              </p>
              <RuleHit
                v-for="r in fee.evaluated"
                :key="r.rule_id"
                :hit="{
                  passed: r.passed,
                  code: 'CHANGE_FEE',
                  description: r.description + ` → 手续费 ${r.fee}`,
                  expression: r.expression,
                  expression2: '',
                  fare_code: '原运价',
                  version_number: r.version_number,
                  version_id: r.version_id,
                }"
              />
              <p class="notice">
                命中规则 #{{ fee.matched_rule_id }}，手续费
                <b class="money-big">{{ cny(fee.fee) }}</b>
              </p>
            </div>
          </div>
        </div>

        <div class="panel" v-if="cmp">
          <h3>价差、税差与应收（全程 Decimal 核算）</h3>
          <table>
            <tbody>
              <tr>
                <td>受影响组件旧运价净额</td>
                <td class="mono">{{ cny(cmp.old_remaining_base) }}</td>
                <td>新行程运价净额</td>
                <td class="mono">{{ cny(cmp.new_base) }}</td>
                <td><b>运价净差</b></td>
                <td class="mono" :class="cmp.base_fare_diff.startsWith('-') ? 'badge bad' : 'badge ok'">
                  {{ cny(cmp.base_fare_diff) }}
                </td>
              </tr>
              <tr>
                <td>旧税（受影响票联）</td>
                <td class="mono">{{ cny(cmp.old_remaining_tax) }}</td>
                <td>新税合计</td>
                <td class="mono">{{ cny(cmp.new_tax.total) }}</td>
                <td><b>税差</b></td>
                <td class="mono">{{ cny(cmp.tax_diff) }}</td>
              </tr>
            </tbody>
          </table>
          <h3 style="margin-top: 12px">新税项明细</h3>
          <table>
            <tbody>
              <tr v-for="t in cmp.new_tax.items" :key="t.code">
                <td><b>{{ t.code }}</b> {{ t.name }}</td>
                <td class="small muted">
                  <span v-for="(p, k) in t.per_segment" :key="k">
                    #{{ p.segment_index + 1 }} {{ cny(p.amount) }}；
                  </span>
                </td>
                <td class="mono">{{ cny(t.total) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="row" style="justify-content: space-between; margin-top: 12px">
            <span class="small muted">
              若价差为负，仅展示可退差额
              <b>{{ cny(cmp.refund_portion_if_any) }}</b>，系统不生成真实退款指令。
            </span>
            <span class="notice">本次改签应收合计
              <b class="money-big">{{ cny(cmp.collect_amount) }}</b>
            </span>
          </div>
        </div>
      </template>

      <p v-if="result.disclaimer" class="notice">{{ result.disclaimer }}</p>
      <p v-if="result.message" class="small muted">{{ result.message }}</p>
    </template>
  </div>
</template>
