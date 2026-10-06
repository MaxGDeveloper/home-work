// Подключение вентилятора
#define pin_PWM 3
#define pin_TECH 2

uint8_t pwm_min = 30;
uint8_t pwm_max = 250;

uint16_t obm_min = 275;
uint16_t obm_max = 2280;

float set_obr = 2280;

float pwm = pwm_min; // из 255
uint16_t T_out = 100;
bool outs = true;

float obm;
uint8_t n_imp = 1;
volatile uint32_t tim_imp;
volatile bool flag_taho = false;

void taho()
{
  static uint32_t tmr_imp;
  static uint8_t imp;
  imp++;
  if (imp >= n_imp * 2) {
    tim_imp = micros() - tmr_imp;
    tmr_imp = micros();
    imp = 0;
    flag_taho = true;
  }
}

void uprput()
{
  static bool impb;
  if (flag_taho) {
    obm = filter(60000000.0 / tim_imp * n_imp) - obm_min;
    flag_taho = false;
    impb = !impb;
    digitalWrite(13, impb);
  }
}

void output() 
{
  static uint32_t tmr_out;
  if (outs && millis() - tmr_out > T_out) {
    tmr_out = millis();
    
    Serial.print(pwm);
    Serial.print(" ");
    Serial.print(obm);
    Serial.print(" ");
    Serial.print(set_obr);
    Serial.println(); 
  }
}

void terminal()
{
  static char cmd[20];
  static int index = 0;
  if(Serial.available())
  {
    char ch = (char)Serial.read();
    if(ch == '\r' || ch == '\n')
    {
      cmd[index] = 0;
      index = 0;

      if(strncmp(cmd, "pwm", 3) == 0)
      {
        pwm = constrain(atoi(cmd + 3), -5, pwm_max - pwm_min);
        analogWrite(pin_PWM, constrain(pwm + pwm_min, 0, 255));
        return;
      }

      if(strncmp(cmd, "out", 3) == 0) {
        if(atoi(cmd + 3) != 0) {
          T_out = constrain(atoi(cmd + 3), 10, 2000);
        }
        else outs = !outs;
        return;
      }

      if(strncmp(cmd, "imp", 3) == 0) {
          n_imp = constrain(atoi(cmd + 3), 10, 100);
        return;
      }

      if(strncmp(cmd, "set", 3) == 0)
      {
        set_obr = constrain(atoi(cmd + 3), 0, obm_max);
        pwm = set_obr / 9.8895;
        analogWrite(pin_PWM, constrain(pwm + pwm_min, 0, 255));
        return;
      }

      if(strncmp(cmd, "sta", 3) == 0) {
          T_out = 1000;
          n_imp = 10;
        return;
      }

      if(strncmp(cmd, "din", 3) == 0) {
          T_out = 100;
          n_imp = 1;
        return;
      }
    }
    else
    {
      cmd[index++] = ch;
    }
  }
}

float filter(float newVal) {
  static float buf[3];
  static byte count = 0;
  buf[count] = newVal;
  if (++count >= 3) count = 0;
  return (max(buf[0], buf[1]) == max(buf[1], buf[2])) ? max(buf[0], buf[2]) : max(buf[1], min(buf[0], buf[2]));
}


void setup() {
  Serial.begin(9600);
  pinMode(pin_PWM, OUTPUT);
  pinMode(pin_TECH, INPUT_PULLUP);

  attachInterrupt(0, taho, RISING);
  analogWrite(pin_PWM, pwm);
}

void loop() {
  // put your main code here, to run repeatedly:
  terminal();
  output();
  uprput();
}
