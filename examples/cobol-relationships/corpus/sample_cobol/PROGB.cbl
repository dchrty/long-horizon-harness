       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
      *
      * Validates a customer record passed by PROGA. Calls PROGC to
      * apply a credit-check side-effect. Pulls layout from BAR.
      *
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CREDIT-LIMIT   PIC 9(05) VALUE 00000.
       LINKAGE SECTION.
       01  L-CUST-RECORD.
           COPY BAR.
       01  L-VALID-FLAG      PIC X(01).
       PROCEDURE DIVISION USING L-CUST-RECORD L-VALID-FLAG.
       MAIN-PARA.
           IF L-CUST-ID > ZERO
               CALL 'PROGC' USING L-CUST-RECORD WS-CREDIT-LIMIT
               MOVE 'Y' TO L-VALID-FLAG
           ELSE
               MOVE 'N' TO L-VALID-FLAG
           END-IF.
           GOBACK.
