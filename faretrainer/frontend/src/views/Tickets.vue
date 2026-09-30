<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const tickets = ref([])
const flights = ref([])
const selected = ref(null)
const changeResult = ref(null)
const changeError = ref('')
const newTicket = ref(null)
const newLegs = ref([])

async function refresh() {
  tickets.value = await api.tickets()
}
onMounted(async () => {
  await refresh()
  flights.value = await api.flights()
})

function cabinOptions(fid) {
  return flights.value.find((f) => f.id === fid)?.cabins || []
}

function startChange(t) {
  selected.value = t
  changeResult.value = null
  changeError.value = ''
  newTicket.value = null
  newLegs.value = t.coupons.map((c) => ({
    flight_id: c.flight_id,
    booking_class: c.booking_class,
  }))
}

async function submitChange() {
  changeError.value = ''
  changeResult.value = null
  try {
    changeResult.value = await api.change({
      ticket_no: selected.value.ticket_no,
      new_flight_ids: newLegs.value.map((l) => l.flight_id),
      new_booking_classes: newLegs.value.map((l) => l.booking_class),
      booking_date: '2026-09-25',
    })
  } catch (e) {
    // 409 = 票联不通过或无可用组合；payload 里有完整明细
    changeResult.value = e.payload
    changeError.value = e.message
  }
}

async function doCommit() {
  newTicket.value = await api.commit(changeResult.value.id)
  await refresh()
}

// 教学辅助：把第一张票联标 USED，演示改签被前置检查拦下
async function markUsed() {
  // 仅为教学演示需要，沙箱没有直接改票联的接口；
  // 这里通过“对已换开票再改”自然触发 EXCHANGED 阻断。
  changeError.value = '可先对一张票执行一次培训换开，再尝试改第二次，'
    + '旧票联全部为 EXCHANGED，改签将在计价前终止。'
}
</script>

<template>
  <div class="grid two">
    <div class="card">
      <h2>培训票（TRN- 虚构票号）</h2>
      <p class="muted small">
        所有票据仅存在于沙箱 PostgreSQL；系统不向任何订座 / 出票 / 支付
        / 退款通道发送指令。
      </p>
      <div v-for="t in tickets" :key="t.ticket_no" class="candidate">
        <div style="display:flex;justify-content:space-between">
          <strong>{{ t.ticket_no }}</strong>
          <span class="badge" :class="t.status === 'ISSUED' ? 'ok' : 'warn'">
            {{ t.status_label }}
          </span>
        </div>
        <div class="small muted">
          报价单 #{{ t.quote }} · 含税 <b class="money">¥{{ t.total }}</b>
        </div>
        <table style="margin-top:6px">
          <tbody>
            <tr v-for="c in t.coupons" :key="c.seq">
              <td>票联{{ c.seq + 1 }}</td>
              <td>{{ c.flight }}</td>
              <td>{{ c.booking_class }}舱</td>
              <td>
                <span class="badge" :class="c.status === 'OPEN' ? 'ok' : 'fail'">
                  {{ c.status_label }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <button
          class="btn secondary"
          style="margin-top:8px"
          :disabled="t.status !== 'ISSUED'"
          @click="startChange(t)"
        >{{ t.status === 'ISSUED' ? '发起改签试算' : '非 ISSUED，不可再改' }}</button>
      </div>
    </div>

    <div v-if="selected" class="card">
      <h2>改签 {{ selected.ticket_no }}</h2>
      <p class="muted small">
        顺序固定：<b>① 剩余票联状态检查 → ② 新行程运价试算 →
        ③ 价差 + 手续费（税在新报价单列示）</b>。
      </p>

      <h3>第①步后的票联检查结果</h3>
      <p v-if="!changeResult" class="muted small">
        提交后先做票联检查；任一票联不是 OPEN，计价根本不会执行。
      </p>

      <h3>选择新行程（第②步的输入）</h3>
      <div v-for="(l, i) in newLegs" :key="i" class="seg-row">
        <strong>段{{ i + 1 }}</strong>
        <select v-model.number="l.flight_id">
          <option v-for="f in flights" :key="f.id" :value="f.id">
            {{ f.carrier }}{{ f.flight_no }} {{ f.dep_airport }}-{{ f.arr_airport }}
            {{ f.dep_local }}
          </option>
        </select>
        <select v-model="l.booking_class">
          <option
            v-for="c in cabinOptions(l.flight_id)"
            :key="c.booking_class"
            :value="c.booking_class"
            :disabled="!c.available"
          >{{ c.booking_class }}舱 · {{ c.seats }}座 · {{ c.status }}</option>
        </select>
      </div>

      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn" @click="submitChange">执行改签试算</button>
        <button class="btn secondary" @click="markUsed">如何演示票联阻断？</button>
      </div>

      <p v-if="changeError" class="banner fail" style="margin-top:12px">
        改签被阻断：{{ changeError }}
      </p>

      <template v-if="changeResult">
        <h3>票联状态检查</h3>
        <table>
          <tbody>
            <tr v-for="row in changeResult.coupon_check" :key="row.seq">
              <td>票联{{ row.seq + 1 }} · {{ row.flight }}</td>
              <td>
                <span class="badge" :class="row.changeable ? 'ok' : 'fail'">
                  {{ row.status_label }}
                </span>
              </td>
              <td class="muted small">{{ row.reason || '可以换开' }}</td>
            </tr>
          </tbody>
        </table>

        <template v-if="changeResult.status === 'OK'">
          <div class="totals" style="margin-top:12px">
            <div class="t muted">原含税总价
              <b class="money">¥{{ changeResult.original_total }}</b></div>
            <div class="t muted">新含税总价（税已重算分列）
              <b class="money">¥{{ changeResult.new_total }}</b></div>
            <div class="t muted">价差
              <b class="money">¥{{ changeResult.fare_diff }}</b></div>
            <div class="t muted">手续费
              <b class="money">¥{{ changeResult.change_fee }}</b></div>
            <div class="t">应补收 / (退还)
              <b class="money" style="font-size:20px">
                ¥{{ changeResult.collect_or_refund }}
              </b></div>
          </div>
          <p class="muted small">{{ changeResult.note }}</p>
          <button class="btn" @click="doCommit">
            执行培训换开（只改沙箱票联状态）
          </button>
          <p v-if="newTicket" class="banner ok" style="margin-top:10px">
            已生成新培训票 {{ newTicket.ticket_no }}；
            旧票联全部置为 EXCHANGED，再次改签将被票联前置检查拦下。
          </p>
        </template>
      </template>
    </div>
  </div>
</template>
