<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const flights = ref([])
const airports = ref([])
const taxes = ref([])

onMounted(async () => {
  [flights.value, airports.value, taxes.value] = await Promise.all([
    api.flights(), api.airports(), api.taxes(),
  ])
})
</script>

<template>
  <div class="grid">
    <div class="card">
      <h2>虚构航班与舱位库存</h2>
      <p class="muted small">
        时刻同时给出 UTC 与机场当地时间；<code class="mono">CLOSED / 余座 0</code>
        的舱位会被硬规则 HARD-AVAILABILITY 直接拦下（表达式规则无法绕过）。
      </p>
      <table>
        <thead>
          <tr>
            <th>航班</th><th>航段</th><th>当地起飞</th><th>当地到达</th>
            <th>UTC</th><th>舱位库存</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in flights" :key="f.id">
            <td><b>{{ f.carrier }}{{ f.flight_no }}</b></td>
            <td>{{ f.dep_airport }} → {{ f.arr_airport }}</td>
            <td>{{ f.dep_local }}</td>
            <td>{{ f.arr_local }}</td>
            <td class="small muted">
              {{ f.dep_utc.replace('T', ' ').slice(0, 16) }} →
              {{ f.arr_utc.replace('T', ' ').slice(0, 16) }}
            </td>
            <td>
              <span
                v-for="c in f.cabins"
                :key="c.booking_class"
                class="badge"
                style="margin:1px"
                :class="c.available ? 'ok' : 'fail'"
              >{{ c.booking_class }}:{{ c.seats }}/{{ c.status }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="grid two">
      <div class="card">
        <h2>机场（本地时区）</h2>
        <table>
          <tbody>
            <tr v-for="a in airports" :key="a.code">
              <td><b>{{ a.code }}</b></td>
              <td>{{ a.name }}</td>
              <td class="muted small">{{ a.timezone }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h2>税项（始终分列）</h2>
        <table>
          <tbody>
            <tr v-for="t in taxes" :key="t.code">
              <td><code class="mono">{{ t.code }}</code></td>
              <td>{{ t.name }}</td>
              <td class="small muted">{{ t.kind_label }}</td>
              <td class="money">¥{{ t.amount }}<span v-if="t.kind==='PERCENT_OF_BASE'">%</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
