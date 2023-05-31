import datetime
from typing import Union, Optional

from kazexapi.request.discount.models import Conditions
from sqlalchemy.util import asyncio

from crud.algorithms.models import CheckResult
from crud.bin import get_lower_bin, get_lower_bin_by_competitor
from database import Bin
from utils import dt

MIN_TIME_BETWEEN_PRICE_CHANGING = 60 * 60  # час


class SalesAccelerationAlgorithm:
    def __init__(self, main_algo):
        super().__init__()
        self.main_algo = main_algo

    async def init(self):
        pass

    def add_to_path(func):
        def wrapper(self, *args, **kwargs):
            result: CheckResult = func(self, *args, **kwargs)
            if result.path is not None:
                self.main_algo.product_db_data.result.path += result.path
            if result.text is not None:
                self.main_algo.product_db_data.result.text += result.text
            if result.full_text is not None:
                self.main_algo.product_db_data.result.text = result.full_text
            return result.result

        return wrapper

    @add_to_path
    def is_best_competitor_price__greater__then_our_price(self):
        if self.main_algo.product_db_data.competitors[0].price > self.main_algo.product_db.last_price:
            return CheckResult(path="Цена конкурента > цена наша,",
                               result=True)
        else:
            return CheckResult(path="Цена конкурента <= цена наша,",
                               result=False)

    @add_to_path
    def is_new_bin__greater_then__min_price(self, new_bin: Optional[Bin]):
        if new_bin:
            return CheckResult(path="Выбранный бин > min цены,",
                               result=True)
        else:
            return CheckResult(path="Выбранный бин <= min цены,",
                               result=False)

    @add_to_path
    def is_in_top100search_results_of_calendar_event(self):
        involved_calendar_events = [p for p in self.main_algo.product_db.participations_in_calendar_event if p.is_involved is True]
        if involved_calendar_events:
            position = involved_calendar_events[0].search_position
            if position and position <= 100:  # TODO: сделать запрос и добавить поле в продукт
                return CheckResult(path="skuid находится в топ 100 выдачи распродажи/подборки,",
                                   result=True)
        return CheckResult(path="skuid НЕ находится в топ 100 выдачи распродажи/подборки,",
                           result=False)

    @add_to_path
    def is_price_calculated_for_every_sku_in_product(self):
        # for product in self.main_algo.sku_list:
        #     if product.sku_id != self.main_algo.product_db.sku_id and \
        #             (dt.now() - dt.with_tz(product.price_update_datetime)).days >= MIN_TIME_BETWEEN_PRICE_CHANGING:
        #         return CheckResult(path="НЕ для всех skuid одного prodid подсчитана цена,",
        #                            result=False)
        # return CheckResult(path="Для всех skuid одного prodid подсчитана цена,",
        #                    result=True)
        if self.main_algo.sku_list[-1].sku_id == self.main_algo.product_db.sku_id and self.main_algo.ran_for_product:
            return CheckResult(path="Для всех skuid одного prodid подсчитана цена,", result=True)
        else:
            return CheckResult(path="НЕ для всех skuid одного prodid подсчитана цена,", result=False)

    @add_to_path
    def has_free_timer_discounts(self):
        if self.main_algo.product_db.shop.quantity_available_timer_discounts > 0:
            return CheckResult(path=f"Есть не занятые акции с таймером,",
                               result=True)
        else:
            return CheckResult(path=f"Все акции с таймером заняты,",
                               result=False)

    @add_to_path
    def is_max_price_timer_discount__greater_then__new_price(self):
        print(self.main_algo.product_db_data.result.product.sku.price.new, flush=True)
        if self.main_algo.product_db_data.timer_discount_condition.max_price > self.main_algo.product_db_data.result.product.sku.price.new:
            return CheckResult(path=f"Максимальная цена акции > планируемая цена,",
                               result=True)
        else:
            return CheckResult(path=f"Максимальная цена акции <= планируемая цена,",
                               result=False)

    @add_to_path
    def is_max_price_timer_discount__greater_then__min_price(self):
        if self.main_algo.product_db_data.timer_discount_condition.max_price > self.main_algo.product_db.min_price:
            return CheckResult(path=f"Максимальная цена акции > минимаьная цена,",
                               result=True)
        else:
            return CheckResult(path=f"Максимальная цена акции <= минимальная цена,",
                               result=False)

    @add_to_path
    def is_max_price_calendar_event__greater_then__new_price(self):
        rp = self.main_algo.product_db.most_suitable_calendar_event.recommended_price
        if rp > self.main_algo.product_db_data.result.product.sku.price.new:
            return CheckResult(path=f"Максимальная цена акции > планируемая цена,",
                               result=True)
        else:
            return CheckResult(path=f"Максимальная цена акции <= планируемая цена,",
                               result=False)

    @add_to_path
    def is_max_price_calendar_event__greater_then__min_price(self):
        rp = self.main_algo.product_db.most_suitable_calendar_event.recommended_price
        if rp > self.main_algo.product_db.min_price:
            return CheckResult(path=f"Максимальная цена акции > минимальная цена,",
                               result=True)
        else:
            return CheckResult(path=f"Максимальная цена акции <= минимальная цена,",
                               result=False)
        

    @add_to_path
    def is_sku_in_timer_discount_more_then_23_hours(self):
        if (self.main_algo.product_db.on_timer_discount) and ((datetime.datetime.now() - self.main_algo.product_db_data.timer_discount.date_start).hours >= 23):
            return CheckResult(path="sku в скидке по таймеру более 23х часов,", result=True)
        else:
            # self.product_db_data.result.product.sku.price.new = self.product_db.min_price
            return CheckResult(path="sku в скидке по таймеру менее 23х часов,", result=False)

    def run(self):
        if self.main_algo.has_best_competitor_link_and_stock():
            if self.main_algo.is_best_competitor_sales_speed__greater_than__our_sales_speed():
                if self.is_best_competitor_price__greater__then_our_price():
                    new_bin = asyncio.run(get_lower_bin(self.main_algo.product_db, self.main_algo.db))
                    self.main_algo.product_db_data.result.text += ('1. Выбираем бин ниже текущего\n'
                                                                   '2. Начало метки "2C."\n')
                    self.main_algo.set_mark("2С")
                else:
                    new_bin = asyncio.run(
                        get_lower_bin_by_competitor(self.main_algo.product_db.sku_id, self.main_algo.competitors[0],
                                                    self.main_algo.db))
                    self.main_algo.product_db_data.result.text += ('1. Выбираем бин ниже текущего\n'
                                                                   '2. Начало метки "2D."\n')
                    self.main_algo.set_mark("2D")
            else:
                self.main_algo.send_message('Продаем быстрее, ставим цену на бин ниже.')
                """
                Оповещаем в чат о том, что продаем быстрее и собираемся понизить цену. Логика в том, что возможно план высокий по продажам, либо конкурент не тот
                """
                self.main_algo.product_db_data.result.text += ('Оповещаем в чат о том, что продаем быстрее и собираемся понизить цену\n'
                                                               '1. Выбираем бин ниже текущего\n'
                                                               '2. Начало метки "2B."\n')
                new_bin = asyncio.run(get_lower_bin(self.main_algo.product_db, self.main_algo.db))
                self.main_algo.set_mark("2B")
        else:
            new_bin = asyncio.run(get_lower_bin(self.main_algo.product_db, self.main_algo.db))
            self.main_algo.product_db_data.result.text += ('1. Выбираем бин ниже текущего\n'
                                                           '2. Начало метки "2A."\n')
            self.main_algo.set_mark("2A")

        if self.is_new_bin__greater_then__min_price(new_bin):
            self.main_algo.set_new_price(new_bin.to_value)
        else:
            self.main_algo.set_new_price(self.main_algo.product_db.min_price)
            self.main_algo.product_db_data.result.text += ('1. Сохраняем min цену для как планируемую к изменению для skuid\n'
                                                           '2. Начало метки "2MIN."\n')
            self.main_algo.set_mark("2MIN")

        self.work_with_calendar_events_and_timer_discounts()

    def work_with_calendar_events_and_timer_discounts(self):
        if self.main_algo.is_sku_in_calendar_event():
            if self.is_in_top100search_results_of_calendar_event():
                self.main_algo.send_message(f'Сегодня ничего не делаем со всеми {self.main_algo.product_db.sku_id} этого {self.main_algo.product_db.product_id}')
                """Оповещаем в чат и ничего не делаем со всем skuid одного prodid в этот день"""
                self.main_algo.product_db_data.result.text += ('1. Оповещаем в чат и ничего не делаем со всем skuid одного prodid в этот день\n'
                                                               '2. Конец метки 1\n')
                self.main_algo.update_mark("1")
            else:
                if self.is_price_calculated_for_every_sku_in_product():
                    self.main_algo.remove_product_from_calendar_event()
                    self.main_algo.add_product_to_calendar_event()
                    """убираем из распродажи и вставляем заново prodid"""
                    self.main_algo.product_db_data.result.text += ('Убираем из распродажи и вставляем заново prodid\n')
                    self.main_algo.update_mark("2")
                else:
                    """Переходим к подсчетам для следующего skuid, относящего к одному prodid"""
                    self.main_algo.set_new_price(None)
                    self.main_algo.product_db_data.result.text += ('Переходим к подсчетам для следующего skuid, относящего к одному prodid\n')
        else:
            if self.main_algo.is_sku_in_timer_discount():
                if self.is_sku_in_timer_discount_more_then_23_hours:
                    '''Вынимаем из акции, и меняем цену на планируемую без повторного вхождения в акцию с таймером.'''
                    self.main_algo.remove_sku_from_timer_discount(self.main_algo.product_db_data.timer_discount.discount_id)
                    self.main_algo.set_new_price(self.main_algo.product_db_data.result.product.sku.price.new)
                    self.main_algo.product_db_data.result.text += ('Вынимаем из акции и меняем цену на планируемую без повторного вхождения в акцию с таймером.\n')
                    self.main_algo.update_mark("3B")
                else:
                    """Ничего не делаем, дожидаемся завершения акции с таймером"""
                    self.main_algo.product_db_data.result.text += ('Ничего не делаем, дожидаемся завершения акции с таймером\n')
                    self.main_algo.update_mark("3A")
                    self.main_algo.set_new_price(None)
            else:
                if self.main_algo.can_be_added_to_any_calendar_event():
                    if self.is_max_price_calendar_event__greater_then__new_price():
                        self.main_algo.set_new_calendar_event_price(
                            self.main_algo.product_db_data.result.product.sku.price.new)
                        if self.main_algo.is_price_for_calendar_event_calculated_for_every_sku_in_product():
                            self.main_algo.add_product_to_calendar_event()
                            self.main_algo.update_mark("8")
                            self.main_algo.product_db_data.result.text += "Вставляем в распродажу весь продукт\n"
                        else:
                            # self.main_algo.set_new_price(None)
                            self.main_algo.product_db_data.result.text += "Переходим к следующему ску\n"

                    else:
                        if self.is_max_price_calendar_event__greater_then__min_price():
                            self.main_algo.set_new_calendar_event_price(self.main_algo.product_db.most_suitable_calendar_event.recommended_price)
                            if self.main_algo.is_price_for_calendar_event_calculated_for_every_sku_in_product():
                                # self.main_algo.set_new_price(
                                #     self.main_algo.product_db_data.result.product.sku.price.for_calendar_event)
                                self.main_algo.add_product_to_calendar_event()
                                self.main_algo.update_mark("10")
                                self.main_algo.product_db_data.result.text += "Вставляем в распродажу весь продукт\n"
                            else:
                                # self.main_algo.set_new_price(None)
                                self.main_algo.product_db_data.result.text += "Переходим к следующему ску\n"
                        else:
                            """Оповещаем в чат о том, что есть позиции, которые не могут быть добавлены в распродажу из-за того, что будет нарушена граница минимальной цены. Необходимо перевести в ручное управление"""
                            self.main_algo.send_message('Есть позиции, которые не могут быть добавлены в распродажу из-за того, что будет нарушена граница минимальной цены.\n'
                                                        f'Необходимо перевести в ручное управление. {self.main_algo.get_responsible_person_username()}\n'
                                                        f'ЦЕНУ НЕ МЕНЯЕМ НИ В ОДНОМ СКУ ЭТОГО ПРОДУКТА\n')
                            self.main_algo.product_db_data.result.text += (f'Оповещаем в чат о том, что есть позиции, которые не могут быть добавлены в распродажу из-за того, что будет нарушена граница минимальной цены.\n'
                                                                           f' Необходимо перевести в ручное управление. {self.main_algo.get_responsible_person_username()}\n'
                                                                           f'ЦЕНУ НЕ МЕНЯЕМ НИ В ОДНОМ СКУ ЭТОГО ПРОДУКТА\n')
                            self.main_algo.update_mark("9")
                            self.main_algo.set_new_price_for_product(None)
                else:
                    if self.has_free_timer_discounts():
                        if self.is_max_price_timer_discount__greater_then__new_price():
                            if self.main_algo.product_db.top:
                                '''Добавляем в акцию с таймером на 48 часов с планируемой ценой в ближайший доступный интервал времени'''
                                self.main_algo.add_sku_to_timer_discount(for_hours=48)
                                self.main_algo.product_db_data.result.text += ('1. Меняем цену на планируемую без участия\n2. Конец метки 4A\n')
                                self.main_algo.update_mark("4A")
                            else:
                                self.main_algo.set_new_price(self.main_algo.product_db_data.result.product.sku.price.new)
                                self.main_algo.product_db_data.result.text += ('1. Добавляем в акцию с таймером на 48 часов с планируемой ценой в ближайший доступный интервал времени\n2.Оповещаем о своем действии в ча\n3. Конец метки 4B\n')
                                self.main_algo.update_mark("4B")
                        else:
                            if self.is_max_price_timer_discount__greater_then__min_price():
                                if self.main_algo.product_db.top:
                                    self.main_algo.set_new_price(self.main_algo.product_db_data.timer_discount_condition.max_price)
                                    self.main_algo.add_sku_to_timer_discount(for_hours=48)
                                    self.main_algo.product_db_data.result.text += ('1. Добавляем в акцию с таймером по максимальной цене с таймером\n2. Конец метки 6A\n3. Переходим к след skuid\n')
                                    self.main_algo.update_mark("6A")
                                else:
                                    self.main_algo.set_new_price(self.main_algo.product_db_data.result.product.sku.price.new)
                                    self.main_algo.product_db_data.result.text += ('1. Меняем цену на планируемую без участия\n2. Конец метки 6B\n')
                                    self.main_algo.update_mark("6B")

                            else:
                                """Оповещаем в чат о том, что данный skuid не может быть добавлен в акцию с таймером из-за того, что будет нарушена граница минимальной цены. Необходимо перевести в ручное управление\n"""
                                self.main_algo.update_mark("5")
                                # self.main_algo.set_new_price(None)
                                self.main_algo.product_db_data.result.text += (f'1. Данный skuid не может быть добавлен в акцию с таймером из-за того, что будет нарушена граница минимальной цены.\nНеобходимо перевести в ручное управление. {self.main_algo.get_responsible_person_username()}\n'
                                                                               f'2. Меняем цену на планируемую без участия в акции.\n')
                    else:
                        self.main_algo.update_mark("7")
