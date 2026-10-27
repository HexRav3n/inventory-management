<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <label for="budget-slider" class="stat-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
        />
        <div class="budget-range">
          <span>{{ formatCurrency(0, currentCurrency) }}</span>
          <span>{{ formatCurrency(maxBudget, currentCurrency) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ formatCurrency(totalCost, currentCurrency) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatCurrency(remainingBudget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.leadTimeDays', { days: estimatedLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="placedOrder" class="notice success-notice">
        <span>{{ t('restocking.orderPlaced', { orderNumber: placedOrder.order_number }) }}</span>
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noItems') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in recommendations" :key="line.sku">
                <td><strong>{{ line.sku }}</strong></td>
                <td>{{ translateProductName(line.name) }}</td>
                <td><span :class="['badge', line.trend]">{{ t(`trends.${line.trend}`) }}</span></td>
                <td class="num">
                  {{ line.quantity.toLocaleString() }}
                  <span v-if="line.quantity < line.forecastedDemand" class="partial">
                    / {{ line.forecastedDemand.toLocaleString() }}
                  </span>
                </td>
                <td class="num">{{ formatCurrencyWithDecimals(line.unitCost, currentCurrency, 2) }}</td>
                <td class="num"><strong>{{ formatCurrency(line.lineTotal, currentCurrency) }}</strong></td>
                <td class="num">{{ t('restocking.leadTimeDays', { days: line.leadTimeDays }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_STEP = 500
const TREND_PRIORITY = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    // Slider tops out at the cost of restocking every forecast item in full
    const maxBudget = computed(() => {
      const fullCost = forecasts.value.reduce((sum, f) => sum + f.forecasted_demand * f.unit_cost, 0)
      return Math.ceil(fullCost / 1000) * 1000
    })

    const growthRate = (forecast) => {
      return (forecast.forecasted_demand - forecast.current_demand) / forecast.current_demand
    }

    // Greedy allocation: fund growing demand first (fastest growth leading), then
    // stable, then shrinking. Each item targets its full forecasted demand; when
    // the budget can't cover that, buy as many units as still fit. Math is done
    // in integer cents so the total never drifts above the budget the server checks.
    const recommendations = computed(() => {
      const prioritized = [...forecasts.value].sort((a, b) => {
        const byTrend = (TREND_PRIORITY[a.trend] ?? 3) - (TREND_PRIORITY[b.trend] ?? 3)
        return byTrend !== 0 ? byTrend : growthRate(b) - growthRate(a)
      })

      let remainingCents = Math.round(budget.value * 100)
      const lines = []

      for (const forecast of prioritized) {
        const unitCents = Math.round(forecast.unit_cost * 100)
        const quantity = Math.min(forecast.forecasted_demand, Math.floor(remainingCents / unitCents))
        if (quantity <= 0) continue

        const lineCents = quantity * unitCents
        remainingCents -= lineCents
        lines.push({
          sku: forecast.item_sku,
          name: forecast.item_name,
          trend: forecast.trend,
          quantity,
          forecastedDemand: forecast.forecasted_demand,
          unitCost: forecast.unit_cost,
          lineTotal: lineCents / 100,
          leadTimeDays: forecast.lead_time_days
        })
      }

      return lines
    })

    const totalCost = computed(() => {
      return recommendations.value.reduce((sum, line) => sum + line.lineTotal, 0)
    })

    const remainingBudget = computed(() => budget.value - totalCost.value)

    // Lines ship together, so the order arrives with its slowest item
    const estimatedLeadTime = computed(() => {
      return recommendations.value.reduce((max, line) => Math.max(max, line.leadTimeDays), 0)
    })

    const loadForecasts = async () => {
      try {
        loading.value = true
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value / 2 / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      submitting.value = true
      submitError.value = null
      placedOrder.value = null
      try {
        placedOrder.value = await api.createRestockOrder({
          items: recommendations.value.map(line => ({ sku: line.sku, quantity: line.quantity })),
          budget: budget.value
        })
      } catch (err) {
        const detail = err.response?.data?.detail || err.message
        submitError.value = `${t('restocking.orderFailed')}: ${detail}`
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      currentCurrency,
      translateProductName,
      formatCurrency,
      formatCurrencyWithDecimals,
      BUDGET_STEP,
      loading,
      error,
      budget,
      maxBudget,
      recommendations,
      totalCost,
      remainingBudget,
      estimatedLeadTime,
      submitting,
      submitError,
      placedOrder,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-header .stat-label {
  margin-bottom: 0;
}

.budget-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-slider {
  width: 100%;
  accent-color: #2563eb;
  cursor: pointer;
}

.budget-range {
  display: flex;
  justify-content: space-between;
  margin-top: 0.375rem;
  font-size: 0.813rem;
  color: #64748b;
}

.place-order-btn {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.125rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.notice {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border-radius: 8px;
  margin: 0 0 1.25rem;
  font-size: 0.938rem;
}

.success-notice {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}

.success-notice a {
  color: #065f46;
  font-weight: 600;
}

.num {
  text-align: right;
}

.partial {
  color: #94a3b8;
  font-size: 0.813rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}
</style>
